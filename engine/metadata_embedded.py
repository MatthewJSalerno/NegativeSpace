"""Verified JPEG working copies, without publication or catalog activation.

Only a caller-owned staging name is created. The organized original is never passed
as an ExifTool write target. A receipt is evidence for the journaled metadata_photo_save publisher,
not authorization to replace a photo, merge duplicates, or delete a source.
"""
import contextlib
import hashlib
import json
import os
import re
import selectors
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import warnings

from PIL import Image

from engine import metadata_capture, metadata_edits, metadata_writer, xmp

EXIF = b'Exif\0\0'
XMP = b'http://ns.adobe.com/xap/1.0/\0'
EXTENDED_XMP = b'http://ns.adobe.com/xmp/extension/\0'
CHUNK = 65536
MAX_READER_BYTES = 16 * 1024 * 1024
TOOL_TIMEOUT = 120


def _command(args, folder, *, limit=MAX_READER_BYTES):
    # Drain both streams with hard live bounds and a deadline. communicate()
    # would buffer arbitrarily large hostile tag output before we could reject it.
    command = ['exiftool', '-q', *args]
    output, errors = bytearray(), bytearray()
    with subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            deadline = time.monotonic() + TOOL_TIMEOUT
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, (output, limit))
                selector.register(process.stderr, selectors.EVENT_READ, (errors, 4096))
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, TOOL_TIMEOUT)
                    for key, _ in selector.select(remaining):
                        block = os.read(key.fileobj.fileno(), CHUNK)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        target, maximum = key.data
                        if len(target) + len(block) > maximum:
                            raise ValueError('Embedded metadata tool output exceeds its bounded size')
                        target.extend(block)
            process.wait(timeout=max(0.001, deadline-time.monotonic()))
            if process.returncode or errors:
                raise ValueError('Embedded metadata tool refused the file: ' + errors.decode('utf-8', 'replace'))
            return bytes(output)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def _tags(path, folder):
    result = json.loads(_command(['-j', '-G1:4', '-a', '-u', '-U', '-b', '-n', '-struct',
                                 '-api', 'StructFormat=JSONQ', str(path)], folder))
    if len(result) != 1:
        raise ValueError('Expected one embedded metadata record')
    tags = {key:value for key,value in result[0].items() if ':' in key
            and key.split(':')[0] not in ('File', 'System', 'Composite')}
    if any(key.startswith('ExifTool:') and key.endswith((':Error', ':Warning')) for key in tags):
        raise ValueError('Embedded metadata reader reported a warning; original unchanged')
    return tags


def _protected_bytes(path, kind):
    """Stream all JPEG bytes except the one writable metadata block.

    This is an edit-integrity check, not a reusable image-only identity. ICC, IPTC,
    comments, JFIF, unknown APP blocks and encoded scan bytes remain protected.
    APP1 after a scan, extended XMP and extra images/trailers are refused. Pillow
    separately decodes the file; structural framing alone does not prove validity.
    """
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        def exact(count):
            data = stream.read(count)
            if len(data) != count:
                raise ValueError('Truncated JPEG working copy')
            return data
        if exact(2) != b'\xff\xd8':
            raise ValueError('Embedded writing is qualified for JPEG bytes only')
        digest.update(b'\xff\xd8')
        writable = 0
        for _ in range(100000):
            marker = exact(2)
            if marker[0] != 255 or marker[1] in (0, 255, 0xd8, 0xd9):
                raise ValueError('Unsupported JPEG marker layout')
            code = marker[1]
            if code not in (0xc0, 0xc2, 0xc4, 0xdb, 0xdd, 0xda, 0xfe, *range(0xe0,0xf0)):
                raise ValueError('Unsupported JPEG encoding')
            length = exact(2)
            size = int.from_bytes(length, 'big')
            if size < 2:
                raise ValueError('Invalid JPEG segment size')
            payload = exact(size - 2)
            if code == 0xe1 and payload.startswith(EXTENDED_XMP):
                raise ValueError('Extended XMP requires separate writer qualification')
            editable = code == 0xe1 and payload.startswith(EXIF if kind == 'embedded_exif' else XMP)
            if editable:
                writable += 1
                if writable > 1:
                    raise ValueError('Multiple writable JPEG metadata packets require a decision')
            else:
                digest.update(marker + length + payload)
            if code == 0xda:
                # Everything after the first scan header is protected verbatim,
                # including progressive scan headers and the final EOI marker.
                tail = b''
                ended = False
                while block := stream.read(CHUNK):
                    combined = tail + block
                    end = combined.find(b'\xff\xd9')
                    if ended or (end >= 0 and end != len(combined)-2):
                        raise ValueError('JPEG trailer or additional image')
                    ended = end >= 0
                    if b'\xff\xe1' in combined:
                        raise ValueError('Metadata after a JPEG scan is not qualified for editing')
                    digest.update(block)
                    tail = combined[-2:]
                if tail != b'\xff\xd9':
                    raise ValueError('JPEG trailer or missing end marker')
                return digest.hexdigest()
        raise ValueError('JPEG marker limit exceeded')


def _pixels(path):
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as photo:
            if photo.format != 'JPEG' or getattr(photo, 'n_frames', 1) != 1:
                raise ValueError('Only single-image JPEG files are qualified')
            photo.load()
            # Deliberately do not apply Orientation or color management. Rotation
            # metadata may change; the stored samples and ICC bytes must not.
            return photo.size, photo.mode, hashlib.sha256(photo.tobytes()).hexdigest()


def _normalized_fields(source):
    fields = dict(source['fields'])
    for key in ('title', 'caption', 'rights'):
        if key in fields and isinstance(fields[key], str):
            fields[key] = {'x-default':fields[key]}
    return fields


def _verify_metadata(before, after, kind, changes, packet, folder, working, remove_fields=()):
    changed = {item['tag'] for item in metadata_edits._tag_edits(kind, changes)
               + metadata_edits._removal_edits(kind, remove_fields)}
    if kind == 'embedded_xmp':
        # Read the exact packet, not ExifTool's print-converted view: explicit
        # empty arrays, language alternatives and rational GPS stay distinguishable.
        actual = _command(['-b', '-XMP', str(working)], folder, limit=xmp.MAX_BYTES)
        if actual != packet:
            raise ValueError('Embedded XMP packet failed exact read-back')
        protected = lambda tags: {key:value for key,value in tags.items() if not key.startswith('XMP-')}
    else:
        report = metadata_capture.interpret(after)
        if report['issues']:
            raise ValueError('Edited embedded metadata could not be interpreted')
        fields = _normalized_fields(report['sources']['exif'])
        if any(key in fields for key in remove_fields):
            raise ValueError('Requested EXIF removals failed read-back verification')
        if any(key not in fields or fields[key] != value for key,value in changes.items()):
            raise ValueError('Requested EXIF fields failed read-back verification')
        def protected(tags):
            return {key:value for key,value in tags.items()
                    if key.split(':')[0]+':'+key.split(':')[-1] not in changed}
    # Family-4 copy numbers can change when a new IFD introduces another tag
    # with the same name. Compare per-family-1 multisets, retaining every value.
    def instances(tags):
        values = {}
        for key, value in protected(tags).items():
            parts = key.split(':')
            if any(re.fullmatch(r'Copy[0-9]+', part) is None for part in parts[1:-1]):
                raise ValueError('Unsupported metadata instance identifier')
            canonical = parts[0]+':'+parts[-1]
            values.setdefault(canonical, []).append(json.dumps(value, sort_keys=True))
        return {key:sorted(items) for key,items in values.items()}
    old, new = instances(before), instances(after)
    generated = {}
    if kind == 'embedded_exif':
        # ExifTool creates required TIFF/EXIF scaffolding when adding an IFD.
        # These exact defaults may be added, never replace existing values.
        defaults = {'IFD0:YCbCrPositioning':'1', 'ExifIFD:ExifVersion':'0232',
                    'ExifIFD:ComponentsConfiguration':'1 2 3 0', 'ExifIFD:ColorSpace':'65535'}
        for axis in ('X','Y'):
            defaults['IFD0:'+axis+'Resolution'] = json.loads(old.get('JFIF:'+axis+'Resolution', ['"1"'])[0])
        units = json.loads(old.get('JFIF:ResolutionUnit', ['"0"'])[0])
        defaults['IFD0:ResolutionUnit'] = {'0':'1','1':'2','2':'3'}.get(units)
        for key,value in defaults.items():
            if key not in old and new.get(key) == [json.dumps(value)]:
                generated[key] = value
                del new[key]
    if old != new:
        differing = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
        raise ValueError('Unrelated metadata changed: ' + ', '.join(differing[:12]))
    return generated



@contextlib.contextmanager
def _destination(root, relative, name, owned):
    """Hold a no-symlink directory chain while allowing our staging writes."""
    with contextlib.ExitStack() as stack:
        def opened(name, parent=None):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=parent)
            stack.callback(os.close, fd)
            return fd
        parent = opened('/')
        chain = []
        for part in (*Path(os.path.abspath(root)).parts[1:], *relative.parts):
            child = opened(part, parent)
            chain.append((parent, part, child)); parent = child
        directory = parent
        try:
            yield directory
            for parent, component, child in chain:
                named = os.stat(component, dir_fd=parent, follow_symlinks=False)
                held = os.fstat(child)
                if (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino):
                    raise ValueError('Staging directory changed during the edit')
        except BaseException as failure:
            if 'identity' in owned:
                try:
                    named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (named.st_dev, named.st_ino) == owned['identity']:
                        os.unlink(name, dir_fd=directory)
                        os.fsync(directory)
                except FileNotFoundError:
                    pass
                except OSError as cleanup:
                    failure.add_note('Staging cleanup could not be synced: '+str(cleanup))
            raise



def stage(root, photo_relative, staged_relative, *, expected_sha1, kind, changes, remove_fields=()):
    """Create a verified JPEG staging file exclusively; never replace the original.

    Paths stay under the configured root, without symlink traversal. Input must
    match its expected whole-file SHA-1. ExifTool edits only a private working copy.
    Failed verification removes that private copy; a returned staged file belongs
    to the caller and must enter its durable intent/recovery protocol.
    """
    if kind not in ('embedded_exif', 'embedded_xmp'):
        raise ValueError('Expected an explicit embedded primary')
    remove_fields = metadata_edits._removals(remove_fields, changes)
    changes = metadata_edits._changes(changes) if changes or not remove_fields else {}
    edits = metadata_edits._tag_edits(kind, changes) + metadata_edits._removal_edits(kind, remove_fields)
    source = xmp.relative_path(photo_relative)
    staged = xmp.relative_path(staged_relative)
    if source == staged or source.suffix.lower() not in ('.jpg','.jpeg','.jpe','.jfif'):
        raise ValueError('Use a separate staging name for a qualified JPEG file')
    owned = {}
    with _destination(root, staged.parent, staged.name, owned) as directory, \
            metadata_capture.open_source(root, source.as_posix()) as (fd, info):
        parent = Path(f'/proc/{os.getpid()}/fd/{directory}')
        if os.path.lexists(parent / staged.name):
            raise FileExistsError('The staging name is occupied')
        # Two working copies accommodate ExifTool's safe rewrite. Refuse before
        # staging if this lower-bound check fails; write-time ENOSPC also propagates.
        required = 2 * info.st_size + 2 * xmp.MAX_BYTES
        available = shutil.disk_usage(parent).free
        if available < required:
            raise OSError(28, f'Metadata staging needs {required} bytes; {available} available')
        with tempfile.TemporaryDirectory(prefix='.ns-embedded-', dir=parent) as folder:
            folder = Path(folder)
            working = folder / 'working.jpg'
            digest = hashlib.sha1()
            with os.fdopen(os.dup(fd), 'rb') as original, open(working, 'xb') as output:
                while block := original.read(CHUNK):
                    digest.update(block); output.write(block)
            if digest.hexdigest() != expected_sha1:
                raise ValueError('The original no longer matches its catalog hash')
            integrity = _protected_bytes(working, kind)
            before = _tags(working, folder)
            report = metadata_capture.interpret(before)
            if report['issues']:
                raise ValueError('Resolve embedded metadata reader issues before editing')
            existing = report['sources'].get('exif' if kind == 'embedded_exif' else 'embedded_xmp', {'fields':{}})
            existing = _normalized_fields(existing)
            noop = (kind == 'embedded_exif' and not set(remove_fields) & set(existing)
                    and all(existing.get(key) == value for key,value in changes.items()))
            pixels = _pixels(working)
            packet = None
            if kind == 'embedded_xmp':
                original = _command(['-b', '-XMP', str(working)], folder, limit=xmp.MAX_BYTES)
                if remove_fields and not original:
                    raise ValueError('Recorded XMP is missing; original unchanged')
                packet = metadata_writer.sidecar_bytes(original, changes, remove_fields=remove_fields) if original else metadata_edits.first_sidecar(changes)
                # ExifTool's raw XMP writer expects xpacket first, not an XML
                # declaration followed by xpacket. Supply its envelope ourselves
                # so the exact bytes can be verified after insertion.
                if packet.startswith(b'<?xml '):
                    packet = packet[packet.index(b'?>') + 2:]
                if not packet.lstrip().startswith(b'<?xpacket '):
                    packet = (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
                              + packet + b'<?xpacket end="w"?>')
                packet_file = folder / 'edited.xmp'
                packet_file.write_bytes(packet)
                _command(['-overwrite_original', '-XMP<='+str(packet_file), str(working)], folder)
            elif not noop:
                # JSON import avoids ARG_MAX and any option-like value becoming a
                # command-line argument. Tag names are an engine-owned allowlist.
                values = {'SourceFile':str(working)}
                values.update({edit['tag']+'#':edit['value'] for edit in edits if edit['operation']=='set'})
                # ExifTool drops these existing IFD values when its last substantive
                # field is removed. Reassert their exact recorded values so a date
                # removal cannot silently erase color/version information. The normal
                # unrelated-tag and protected-image verification still applies.
                if remove_fields:
                    for tag in ('ExifIFD:ExifVersion','ExifIFD:ComponentsConfiguration','ExifIFD:ColorSpace'):
                        if tag in before:
                            values[tag+'#'] = before[tag]
                removals = ['-'+edit['tag']+'=' for edit in edits if edit['operation']=='remove']
                request = folder / 'changes.json'
                request.write_text(json.dumps([values], ensure_ascii=False), encoding='utf-8')
                _command(['-overwrite_original', '-json='+str(request), *removals, str(working)], folder)
            after = _tags(working, folder)
            generated = _verify_metadata(before, after, kind, changes, packet, folder, working, remove_fields)
            if _protected_bytes(working, kind) != integrity or _pixels(working) != pixels:
                raise ValueError('The metadata writer changed protected image data')
            with open(working, 'rb') as output:
                after_hash = hashlib.file_digest(output, 'sha1').hexdigest()
                os.fsync(output.fileno())
            os.chmod(working, info.st_mode & 0o666)
            with open(working, 'rb') as output:
                os.fsync(output.fileno())
            os.link(working, staged.name, dst_dir_fd=directory, follow_symlinks=False)
            staged_info = working.stat()
            owned['identity'] = (staged_info.st_dev, staged_info.st_ino)
            os.fsync(directory)
            return {'before_sha1':expected_sha1, 'after_sha1':after_hash,
                    'size':working.stat().st_size, 'kind':kind, 'changes':changes,
                    'no_change':after_hash == expected_sha1, 'generated_tags':generated,
                    'tags_before':before, 'tags_after':after,
                    'width':pixels[0][0], 'height':pixels[0][1]}

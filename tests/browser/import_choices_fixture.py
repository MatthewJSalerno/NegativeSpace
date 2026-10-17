"""Generated source-only ownership and competing-version cases."""
from pathlib import Path
import sys
from PIL import Image

root=Path(sys.argv[1])
root.mkdir(parents=True,exist_ok=True)
def packet(date):
    return ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:exif="http://ns.adobe.com/exif/1.0/"><rdf:Description>'
        f'<exif:DateTimeOriginal>{date}</exif:DateTimeOriginal></rdf:Description></rdf:RDF>')
if '--primary-only' in sys.argv:
    import subprocess
    photo=root/'primary-sources.jpg'
    Image.new('RGB',(420,280),(52,107,123)).save(photo)
    subprocess.run(['exiftool','-overwrite_original','-EXIF:DateTimeOriginal=2023:01:15 09:30:00',
        '-XMP-exif:DateTimeOriginal=2022:02:03 04:05:06','-XMP-dc:Title=Primary source example',
        str(photo)],check=True,capture_output=True)
    photo.with_name(photo.name+'.xmp').write_text(packet('2021-02-03T04:05:06'))
    raise SystemExit(0)

if '--duplicates-only' not in sys.argv:
    for name,color in [('choice-shared.jpg',(17,29,83)),('choice-shared.png',(97,46,11)),('choice-versions.jpg',(44,76,93))]:
        Image.new('RGB',(230,440) if name.endswith('.png') else (340,230),color).save(root/name)
    (root/'choice-shared.xmp').write_text(packet('2010-02-03T04:05:06'))
    (root/'choice-versions.xmp').write_text(packet('2011-03-04T05:06:07'))
    (root/'choice-versions.XMP').write_text(packet('2012-04-05T06:07:08'))

# Qualified JPEG pairs: saving the requested field creates an exact whole-file copy.
import hashlib
import subprocess
from engine import metadata_embedded
for kind, color, changes in [('rotate',(81,36,104),{'orientation':6}),
                              ('date',(21,106,73),{'date_taken':'2010-02-03T04:05:06'})]:
    original=root/f'dedup-{kind}-edit.jpg'
    Image.new('RGB',(360,240),color).save(original)
    subprocess.run(['exiftool','-overwrite_original','-EXIF:Orientation#=1',
        '-EXIF:DateTimeOriginal=2001:02:03 04:05:06',str(original)],check=True,capture_output=True)
    metadata_embedded.stage(root,original.name,f'dedup-{kind}-keep.jpg',
        expected_sha1=hashlib.sha1(original.read_bytes()).hexdigest(),kind='embedded_exif',changes=changes)

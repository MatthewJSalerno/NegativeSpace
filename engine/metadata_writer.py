"""Verified field-scoped XMP construction; filesystem publication is separate.

Preserve unmapped properties, arrays, qualifiers and comments. The retained original
is authoritative for its previous exact bytes; editing may change XML serialization.
"""
from xml.dom import Node, minidom

from engine import metadata_adapter, metadata_edits, xmp


def _properties(capture, changed):
    return {name:nodes for name,nodes in capture.tags['properties'].items()
            if xmp.FIELD_TAGS.get(name) not in changed and not ('gps' in changed and name in xmp.GPS_TAGS)}


def sidecar_bytes(original, changes, *, remove_fields=()):
    """Return a verified XMP version with only explicitly requested field changes.

    No files are read or written. Validation precedes DOM parsing, so DTD/entity and
    resource-limit rules cannot be bypassed by the writer. Unknown metadata never
    goes through a lossy flat-tag or ExifTool export/reconstruction step.
    """
    remove_fields=metadata_edits._removals(remove_fields, changes)
    changes=metadata_edits._changes(changes) if changes or not remove_fields else {}
    changed=set(changes) | set(remove_fields)
    before=xmp.parse_bytes(original,source_id='before')
    if before.state!='valid':
        raise ValueError('An existing sidecar must be readable, valid XMP before editing')
    fields=metadata_adapter.for_comparison(before.source).fields
    if not set(remove_fields) & set(fields) and all(key in fields and fields[key]==value for key,value in changes.items()):
        return original
    expected={key:value for key,value in {**fields,**changes}.items() if key not in remove_fields}
    replacement=minidom.parseString(metadata_edits.first_sidecar(changes)) if changes else None
    document=minidom.parseString(original)
    try:
        descriptions=[node for node in document.getElementsByTagNameNS(xmp.RDF,'Description')
            if node.parentNode.namespaceURI==xmp.RDF and node.parentNode.localName=='RDF']
        if not descriptions:
            raise ValueError('No supported XMP metadata subject')
        names={name for name,field in xmp.FIELD_TAGS.items() if field in changed}
        if 'gps' in changed:names.update(xmp.GPS_TAGS)
        for description in descriptions:
            for index in reversed(range(description.attributes.length)):
                attribute=description.attributes.item(index)
                if '{'+(attribute.namespaceURI or '')+'}'+attribute.localName in names:
                    description.removeAttributeNode(attribute)
            for child in list(description.childNodes):
                if child.nodeType==Node.ELEMENT_NODE and '{'+(child.namespaceURI or '')+'}'+child.localName in names:
                    description.removeChild(child);child.unlink()
        source=replacement.getElementsByTagNameNS(xmp.RDF,'Description')[0] if replacement else None
        # Locally declare each imported prefix. This remains correct when the
        # original packet uses a conflicting prefix for an unrelated namespace.
        for child in source.childNodes if source else ():
            if child.nodeType!=Node.ELEMENT_NODE:continue
            imported=document.importNode(child,True)
            imported.setAttributeNS('http://www.w3.org/2000/xmlns/','xmlns:'+child.prefix,child.namespaceURI)
            # Array children also use rdf; the source may bind that prefix differently.
            imported.setAttributeNS('http://www.w3.org/2000/xmlns/','xmlns:rdf',xmp.RDF)
            descriptions[0].appendChild(imported)
        result=document.toxml(encoding='utf-8')
    finally:
        if replacement:
            replacement.unlink()
        document.unlink()
    after=xmp.parse_bytes(result,source_id='after')
    if after.state!='valid' or metadata_adapter.for_comparison(after.source).fields!=expected:
        raise ValueError('XMP edit read-back does not match the intended fields')
    if _properties(before,changed)!=_properties(after,changed):
        raise ValueError('XMP edit would change unrelated metadata')
    return result

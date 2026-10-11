"""Lossless lexical XMP coordinates and linked GPS edit validation.

Coordinates retain their XMP degrees/minutes[/seconds]/hemisphere representation;
no binary-float normalization or location guessing is used. All components belong
to one source, so an incomplete source cannot borrow coordinates from another.
"""
import re
import decimal
from decimal import Decimal

PARTS = {'GPSLatitude':'latitude', 'GPSLongitude':'longitude',
         'GPSAltitude':'altitude', 'GPSAltitudeRef':'altitude_ref'}
_COORDINATE = re.compile(r'([0-9]+),([0-9]+(?:\.[0-9]+)?)(?:,([0-9]+(?:\.[0-9]+)?))?([NSEW])')
_UNSIGNED = re.compile(r'[0-9]+(?:\.[0-9]+)?(?:/[0-9]+)?')
_DECIMAL = re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?')


def validate(value, *, editing=False):
    if not isinstance(value,dict) or not set(value)<=set(PARTS.values()):
        raise ValueError('invalid_gps')
    for key,text in value.items():
        if not isinstance(text,str):raise ValueError('invalid_gps_'+key)
        if text=='':continue  # Retain explicitly empty recorded components.
        if key in ('latitude','longitude'):
            match=_COORDINATE.fullmatch(text)
            if match is None:raise ValueError('invalid_gps_'+key)
            degree,minute,second,hemisphere=match.groups()
            maximum,allowed=(90,'NS') if key=='latitude' else (180,'EW')
            if (hemisphere not in allowed or int(degree)>maximum or Decimal(minute)>=60
                or (second is not None and ('.' in minute or Decimal(second)>=60))
                or (int(degree)==maximum and (Decimal(minute)!=0 or (second is not None and Decimal(second)!=0)))):
                raise ValueError('invalid_gps_'+key)
        elif key=='altitude_ref':
            if text not in ('0','1'):raise ValueError('invalid_gps_altitude_ref')
        elif _UNSIGNED.fullmatch(text) is None or ('/' in text and int(text.split('/')[1])==0):
            raise ValueError('invalid_gps_altitude')
    if editing and value:
        if not value.get('latitude') or not value.get('longitude'):
            raise ValueError('GPS edits require both latitude and longitude, or an empty object to clear both')
        if ('altitude' in value)!=('altitude_ref' in value) or any(text=='' for text in value.values()):
            raise ValueError('GPS altitude and reference must be supplied together')
    return dict(value)


def from_xmp(parts):
    value={PARTS[key]:text for key,text in parts.items()}
    # A paired explicit empty coordinate is the clearing value, not absence.
    if value and all(text=='' for text in value.values()):return {}
    return validate(value)


def coordinate(degree_text, axis, reference=None):
    """Convert ExifTool's decimal-degree text into exact decimal XMP minutes."""
    if not isinstance(degree_text,str) or _DECIMAL.fullmatch(degree_text) is None:
        raise ValueError('invalid_gps_'+axis)
    with decimal.localcontext() as ctx:
        ctx.prec=max(32,len(degree_text)+8)
        number=Decimal(degree_text)
        direction=('S' if number.is_signed() else 'N') if axis=='latitude' else ('W' if number.is_signed() else 'E')
        if reference is not None:
            if not isinstance(reference,str) or len(reference)!=1 or reference not in ('NS' if axis=='latitude' else 'EW'):
                raise ValueError('invalid_gps_reference')
            # EXIF stores an unsigned value plus a separate hemisphere.
            if number<0:raise ValueError('negative_exif_coordinate')
            direction=reference
        absolute=abs(number);degree=int(absolute);minute=(absolute-degree)*60
        result=f'{degree},{format(minute,"f")}{direction}'
    validate({axis:result})
    return result


def from_embedded(values, *, xmp=False):
    prefix='XMP-exif:' if xmp else 'GPS:'
    parts={key:values[prefix+key] for key in PARTS if prefix+key in values}
    for tag,axis in (('GPSLatitude','latitude'),('GPSLongitude','longitude')):
        if tag in parts and parts[tag]!='':
            reference=None if xmp else values.get(prefix+tag+'Ref')
            if not xmp and reference is None:raise ValueError('gps_coordinate_without_reference')
            parts[tag]=coordinate(parts[tag],axis,reference)
        elif not xmp and prefix+tag+'Ref' in values:
            raise ValueError('gps_reference_without_coordinate')
    return from_xmp(parts)

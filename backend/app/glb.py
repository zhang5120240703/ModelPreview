"""A textured test cube. This is never a reconstruction of the uploaded photos."""
import io
import json
import struct
from PIL import Image


def make_test_glb() -> bytes:
    vertices, normals, uvs, indices = [], [], [], []
    faces = [((0,0,1), [(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]),
             ((0,0,-1), [(1,-1,-1),(-1,-1,-1),(-1,1,-1),(1,1,-1)]),
             ((1,0,0), [(1,-1,1),(1,-1,-1),(1,1,-1),(1,1,1)]),
             ((-1,0,0), [(-1,-1,-1),(-1,-1,1),(-1,1,1),(-1,1,-1)]),
             ((0,1,0), [(-1,1,1),(1,1,1),(1,1,-1),(-1,1,-1)]),
             ((0,-1,0), [(-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1)])]
    for normal, corners in faces:
        start = len(vertices) // 3
        for p in corners:
            vertices.extend(p)
            normals.extend(normal)
        uvs.extend([0,0,1,0,1,1,0,1])
        indices.extend(start+i for i in [0,1,2,0,2,3])
    image = Image.new('RGB', (64,64))
    for y in range(64):
        for x in range(64):
            image.putpixel((x,y), (190,145,77) if (x//8+y//8)%2 else (228,193,130))
    png = io.BytesIO()
    image.save(png, format='PNG')
    blobs = [struct.pack('<'+'f'*len(v), *v) for v in (vertices,normals,uvs)]
    blobs += [struct.pack('<'+'H'*len(indices), *indices), png.getvalue()]
    binary, views = b'', []
    for blob in blobs:
        binary += b'\0' * (-len(binary)%4)
        views.append({'buffer':0,'byteOffset':len(binary),'byteLength':len(blob)})
        binary += blob
    document = {'asset':{'version':'2.0','generator':'GrassCraft MOCK test geometry'},
        'scene':0,'scenes':[{'nodes':[0]}], 'nodes':[{'mesh':0,'name':'MOCK textured cube'}],
        'meshes':[{'primitives':[{'attributes':{'POSITION':0,'NORMAL':1,'TEXCOORD_0':2},
                                  'indices':3,'material':0}]}],
        'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0},
                      'metallicFactor':0,'roughnessFactor':0.85}}],
        'textures':[{'source':0}], 'images':[{'bufferView':4,'mimeType':'image/png'}],
        'buffers':[{'byteLength':len(binary)}], 'bufferViews':views,
        'accessors':[{'bufferView':0,'componentType':5126,'count':24,'type':'VEC3','min':[-1,-1,-1],'max':[1,1,1]},
                     {'bufferView':1,'componentType':5126,'count':24,'type':'VEC3'},
                     {'bufferView':2,'componentType':5126,'count':24,'type':'VEC2'},
                     {'bufferView':3,'componentType':5123,'count':36,'type':'SCALAR'}]}
    metadata = json.dumps(document,separators=(',',':')).encode()
    metadata += b' '*(-len(metadata)%4)
    binary += b'\0'*(-len(binary)%4)
    return (struct.pack('<4sII', b'glTF',2,28+len(metadata)+len(binary)) +
            struct.pack('<I4s',len(metadata),b'JSON')+metadata+
            struct.pack('<I4s',len(binary),b'BIN\0')+binary)


def validate_glb(path):
    size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(20)
        if len(header) != 20:
            raise ValueError('模型不是有效 GLB')
        magic, version, length, json_length, chunk = struct.unpack('<4sIII4s', header)
        if magic != b'glTF' or version != 2 or length != size or chunk != b'JSON' or json_length > size-20:
            raise ValueError('模型 GLB 头部无效')
        doc = json.loads(stream.read(json_length))
        if doc.get('asset',{}).get('version') != '2.0' or not doc.get('meshes'):
            raise ValueError('模型缺少 glTF 2.0 网格')
        for item in doc.get('buffers',[]) + doc.get('images',[]):
            uri = item.get('uri','')
            if uri and not uri.startswith('data:'):
                raise ValueError('模型必须是自包含 GLB，不能依赖外部文件')

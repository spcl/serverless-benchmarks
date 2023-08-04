import datetime, json, os, uuid

# Extract zipped torch model - used in Python 3.8 and 3.9
# The reason is that torch versions supported for these Python
# versions are too large for Lambda packages.
if os.path.exists('function/torch.zip'):
    import zipfile, sys
    # we cannot write to the read-only filesystem
    zipfile.ZipFile('function/torch.zip').extractall('/tmp/')
    sys.path.append(os.path.join(os.path.dirname(__file__), '/tmp/.python_packages/lib/site-packages'))

from PIL import Image
import torch
from torchvision import transforms
from torchvision.models import resnet50
from jsonschema import validate

from . import storage
client = storage.storage.get_instance()

SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
class_idx = json.load(open(os.path.join(SCRIPT_DIR, "imagenet_class_index.json"), 'r'))
idx2label = [class_idx[str(k)][1] for k in range(len(class_idx))]
model = None

def handler(event):
  
    scheme = {
        "type": "object",
        "required": ["bucket", "object"],
        "properties": {
            "bucket": {
                "type": "object",
                "required": ["model", "input"]
            },
            "object": {
                "type": "object",
                "required": ["input", "model"]
            }
        }
    }

    try:
        validate(event, schema=scheme)
    except:
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    
    model_bucket = event['bucket']['model']
    input_bucket = event['bucket']['input']
    key = event['object']['input']  # !? it is 'input' or 'key'
    model_key = event['object']['model']
    download_path = f'/tmp/{key}-{uuid.uuid4()}'

    image_download_begin = datetime.datetime.now()
    image_path = download_path
    client.download(input_bucket, key, download_path)
    image_download_end = datetime.datetime.now()

    global model
    if not model:
        model_download_begin = datetime.datetime.now()
        model_path = os.path.join('/tmp', model_key)
        client.download(model_bucket, model_key, model_path)
        model_download_end = datetime.datetime.now()
        model_process_begin = datetime.datetime.now()
        model = resnet50(pretrained=False)
        model.load_state_dict(torch.load(model_path))
        model.eval()
        model_process_end = datetime.datetime.now()
    else:
        model_download_begin = datetime.datetime.now()
        model_download_end = model_download_begin
        model_process_begin = datetime.datetime.now()
        model_process_end = model_process_begin
   
    process_begin = datetime.datetime.now()
    input_image = Image.open(image_path)
    preprocess = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    input_tensor = preprocess(input_image)
    input_batch = input_tensor.unsqueeze(0) # create a mini-batch as expected by the model 
    output = model(input_batch)
    _, index = torch.max(output, 1)
    # The output has unnormalized scores. To get probabilities, you can run a softmax on it.
    prob = torch.nn.functional.softmax(output[0], dim=0)
    _, indices = torch.sort(output, descending = True)
    ret = idx2label[index]
    process_end = datetime.datetime.now()

    download_time = (image_download_end - image_download_begin) / datetime.timedelta(microseconds=1)
    model_download_time = (model_download_end - model_download_begin) / datetime.timedelta(microseconds=1)
    model_process_time = (model_process_end - model_process_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    return {
            'status': 'success',
            'result': 'Returned with no error',
            'measurement': {
                'idx': index.item(),
                'class': ret,
                'download_time': download_time + model_download_time,
                'compute_time': process_time + model_process_time,
                'model_time': model_process_time,
                'model_download_time': model_download_time
            }
        }


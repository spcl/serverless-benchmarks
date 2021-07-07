import json

def lambda_handler(event, context):
    # we may want to compare to reference results
    return {
        'statusCode': 200,
        'time': int(round(time.time() * 1000)),
        'body': 'Got '+str(len(event)) + " frames back"
    }

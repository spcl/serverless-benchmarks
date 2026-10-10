def handler(event):
    count = int(event["count"])
    sleep = int(event["sleep"])
    
    sleep_list = []
    for i in range(0, count):
      sleep_list.append({'sleep':sleep})


    return {
        "buffer": sleep_list
    }

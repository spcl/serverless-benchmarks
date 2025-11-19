def handler(event):
    frames = event["frames"]

    logs = {}
    for xs in frames:
        for key, value in xs.items():
            logs[key] = value

    return logs

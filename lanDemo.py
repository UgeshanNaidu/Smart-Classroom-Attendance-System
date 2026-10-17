import socket
import subprocess

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # The target IP doesn't need to be reachable or exist
        s.connect(('8.8.8.8', 1))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip

subprocess.run(['.venv/scripts/python.exe' , 'httpserver.py' , '--demo' , '--host' , get_local_ip() , '--port' , '8080'])
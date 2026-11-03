from dotenv import load_dotenv
load_dotenv()
from resonance.web import create_app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=8888, debug=False, threaded=True)

import io
from PIL import Image
from fastapi.testclient import TestClient
from app import app

def test_health():
    r=TestClient(app).get('/health')
    assert r.status_code==200 and r.json()['ok']

def test_home():
    r=TestClient(app).get('/')
    assert r.status_code==200 and 'AI MUSIC VIDEO STUDIO' in r.text

def test_consent_required():
    p=io.BytesIO();Image.new('RGB',(32,32)).save(p,'PNG')
    r=TestClient(app).post('/api/jobs',data={'consent':'false'},files={
       'photo':('a.png',p.getvalue(),'image/png'),
       'song':('b.mp3',b'abc','audio/mpeg')})
    assert r.status_code==400

def test_invalid_mode():
    r=TestClient(app).post('/api/jobs',data={'mode':'invalid','consent':'true'},files={
       'photo':('a.png',b'abc','image/png'),
       'song':('b.mp3',b'abc','audio/mpeg')})
    assert r.status_code==400

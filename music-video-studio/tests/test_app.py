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


def test_preview_command_has_memory_limits(monkeypatch,tmp_path):
    import app as studio
    commands=[]
    monkeypatch.setattr(studio,"portrait",lambda a,b: b.write_bytes(b"fake"))
    monkeypatch.setattr(studio,"run",lambda *args:commands.append(args))
    studio.preview(tmp_path/"input.jpg",tmp_path/"song.m4a",tmp_path/"out.mp4",tmp_path)
    command=commands[0]
    assert "zoompan" not in " ".join(map(str,command))
    assert command[command.index("-threads")+1]=="1"
    assert command[command.index("-framerate")+1]=="12"

def test_job_status_recovery_after_restart(tmp_path,monkeypatch):
    import app as studio
    monkeypatch.setattr(studio,"DATA",tmp_path)
    key="a"*32
    studio.jobs[key]={"id":key,"status":"processing","progress":15}
    studio.write_status(key)
    studio.jobs.clear()
    studio.recover_jobs()
    assert studio.jobs[key]["status"]=="failed"
    assert "server restarted" in studio.jobs[key]["error"]

"""Disposable real Redis/ingress + HTTPS mock apps; no production credentials/DB."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile

here = Path(__file__).resolve().parent
image = 'docker.io/kty1021/sample-app:363eeb9298c1cee74d0cbc9dd5d4fb4b172b0c2e'
tools = 'ghcr.io/softbankhackathon2026/migration-tools:cb3a99cb3a7b7b567627f9472c181a68aca467a0'
with tempfile.TemporaryDirectory(prefix='cloud-control-smoke-') as temp:
    fixture = Path(temp)
    for source, target in [('control-fixture-backend.js','backend.js'),('control-fixture-test.py','test.py')]:
        shutil.copy(here/source, fixture/target)
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
        '-keyout',str(fixture/'key.pem'),'-out',str(fixture/'cert.pem'),'-days','1',
        '-subj','/CN=backend','-addext','subjectAltName=DNS:backend'],check=True,capture_output=True)
    (fixture/'key.pem').chmod(0o644)  # ephemeral test-only TLS key, readable by uid1000 fixture
    control = str(here.parent/'control')
    targets={k:{'url':f'https://backend:{port}','token_env':'BACKEND_TOKEN'} for k,port in [('aws',8443),('gcp',8444)]}
    compose={'services':{
        'redis':{'image':'redis:7.4-alpine'},
        'backend':{'image':image,'command':['node','/fixture/backend.js'],'volumes':[temp+':/fixture:ro']},
        'ingress':{'image':image,'command':['node','/control/ingress.js'],
            'volumes':[control+':/control:ro',temp+'/cert.pem:/ca.pem:ro'],
            'environment':{'REDIS_URL':'redis://redis:6379','INGRESS_INITIAL_TARGET':'aws',
                'INGRESS_TARGETS':json.dumps(targets),'INGRESS_API_TOKEN':'local-test-api',
                'INGRESS_CONTROL_TOKEN':'local-test-control','BACKEND_TOKEN':'local-test-backend',
                'NODE_EXTRA_CA_CERTS':'/ca.pem'}}}}
    file=fixture/'compose.json';file.write_text(json.dumps(compose))
    project='ghost-cloud-control-smoke'
    cmd=['docker','compose','-p',project,'-f',str(file)]
    try:
        subprocess.run(cmd+['up','-d'],check=True)
        subprocess.run(['docker','run','--rm','--network',project+'_default','--platform','linux/amd64',
            '-e','PYTHONPATH=/control','-e','SSL_CERT_FILE=/fixture/cert.pem',
            '-v',temp+':/fixture:ro','-v',control+':/control:ro','--entrypoint','python',tools,'/fixture/test.py'],check=True)
    finally:
        subprocess.run(cmd+['down','-v'],check=True)

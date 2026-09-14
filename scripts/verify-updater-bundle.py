import hashlib, json, pathlib, sys, tarfile, subprocess, tempfile
root, version = pathlib.Path(sys.argv[1]), sys.argv[2]
scripts = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(scripts / 'verify-release-manifest.py'), str(root / 'updater-release.json'), str(root / 'updater-release.json.sig.json'), str(scripts.parent / '.release/updater-public-key.pem')], check=True)
manifest = json.loads((root / 'updater-release.json').read_bytes())
name = 'updater-' + version + '-install.tar.gz'
if manifest.get('schema_version') != 1 or manifest.get('service') != 'updater' or manifest.get('version') != version: raise SystemExit('Updater release identity mismatch')
if manifest.get('installer', {}).get('sha256') != hashlib.sha256((root / name).read_bytes()).hexdigest(): raise SystemExit('Signed Updater bundle checksum mismatch')
with tarfile.open(root / name) as archive:
    members = archive.getmembers()
    if len(members) > 128 or sum(m.size for m in members) > 256*1024*1024: raise SystemExit('Updater archive limit exceeded')
    seen = set()
    for member in members:
        p = pathlib.PurePosixPath(member.name)
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] != 'updater' or member.name in seen or not (member.isfile() or member.isdir()): raise SystemExit('Unsafe Updater archive')
        seen.add(member.name)
    required = ['updater/install.sh', 'updater/updater-linux-amd64', 'updater/systemd/updater.service', *['updater/release-trust/' + scope + '.pem' for scope in ['updater','neptune','gryphon']]]
    if any(name not in seen for name in required): raise SystemExit('Incomplete helper installer or trust set')
    binary = archive.extractfile('updater/updater-linux-amd64').read()
    if hashlib.sha256(binary).hexdigest() != manifest.get('binary', {}).get('sha256'): raise SystemExit('Bundled Updater executable differs from its signed digest')
    with tempfile.TemporaryDirectory() as directory:
        binary_path = pathlib.Path(directory) / 'updater'
        binary_path.write_bytes(binary); binary_path.chmod(0o755)
        actual = subprocess.check_output([str(binary_path), 'version'], text=True).strip()
        if actual != version: raise SystemExit('Bundled Updater version mismatch')
print('Verified signed Updater installer', version)

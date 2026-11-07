"""Hash-bound legacy publication restore. Writes new files only; no cleanup or archive creation."""
from __future__ import annotations
import hashlib,json,os,re,stat,zipfile
from pathlib import Path,PurePosixPath,PureWindowsPath

def absolute(path):
    return Path(os.path.abspath(path))



def linked(path):
    """Inspect lexical ancestors BEFORE resolve/stat; never follow a dependency."""
    p = absolute(path)
    for part in (p, *p.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return True
    return False



def relative_path(owner, root, value):
    text = str(value).replace("\\", "/")
    rel = PurePosixPath(text)
    if rel.is_absolute() or PureWindowsPath(text).drive or ".." in rel.parts or text in {"", "."}:
        raise owner.LifecycleError("archive_path_outside_workspace", text)
    candidate = absolute(root / Path(text))
    if not candidate.is_relative_to(root):
        raise owner.LifecycleError("archive_path_outside_workspace", text)
    return candidate, rel.as_posix()



def _new(owner, path):
    path = absolute(path)
    if path.exists() or linked(path):
        raise owner.LifecycleError("archive_output_exists_or_linked", str(path))
    return path



def restore_publication(owner, archive_ref, data_member, output_dir):
    """Adapt legacy desk archives with existing link/hash/disk guards; no rebuild."""
    import publication_desk as desk
    archive = absolute(archive_ref['path'])
    output = _new(owner, output_dir)
    if linked(archive) or not archive.is_file() or owner._sha256(archive) != archive_ref['sha256']:
        raise ValueError('source_archive_missing_changed_or_linked')
    if not output.parent.is_dir():
        raise ValueError('restore_output_parent_must_exist')
    relative_path(owner,output,data_member)
    with zipfile.ZipFile(archive) as package:
        info = package.getinfo(data_member)
        if info.file_size > 2_000_000 or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('bounded_saved_desk_json_required')
        data = desk.upgrade(json.loads(package.read(info).decode('utf-8-sig')))
        assets = [asset for item in data['items'] for asset in [item['video'],*item['covers']]]
        selected = {}
        for asset in assets:
            digest = asset.get('sha256','')
            if not re.fullmatch('[a-f0-9]{64}',digest):
                raise ValueError('archive_asset_requires_saved_sha256')
            if digest in selected:
                continue
            basename = asset['path'].replace('\\','/').rsplit('/',1)[-1]
            suffix = Path(basename).suffix.lower()
            if suffix not in {'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv'}:
                raise ValueError('only_saved_media_assets_may_be_restored')
            matches = [entry for entry in package.infolist() if entry.filename.rsplit('/',1)[-1]==basename and not entry.is_dir()]
            matched = None
            for entry in matches:
                relative_path(owner,output,entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('archive_dependency_link_must_not_be_materialized')
                with package.open(entry) as stream:
                    actual = hashlib.file_digest(stream,'sha256').hexdigest()
                if actual == digest:
                    matched = entry
                    break
            if matched is None:
                raise ValueError('saved_asset_not_found_by_hash_in_archive: '+basename)
            selected[digest] = (matched, suffix)
        core = owner._load_shared_core()
        profile = owner._media_profile(core)
        disk = core.free_space_status(output.parent, minimum_free_bytes=profile['minimum_free_bytes'],
            warning_free_bytes=profile['warning_free_bytes'],output_headroom_multiplier=profile['output_headroom_multiplier'],
            estimated_output_bytes=sum(entry.file_size for entry,_ in selected.values()))
        if disk['status']=='blocked_low_disk':
            raise ValueError('restore_blocked_low_disk')
        (output/'assets').mkdir(parents=True)
        mapping=[]
        for digest,(entry,suffix) in selected.items():
            target = output/'assets'/(digest+suffix)
            with package.open(entry) as stream, target.open('xb') as destination:
                while block := stream.read(1024*1024):
                    destination.write(block)
            if owner._sha256(target) != digest:
                raise ValueError('restored_asset_hash_mismatch')
            for asset in assets:
                if asset['sha256']==digest:
                    mapping.append(dict(old_path=asset['path'],new_path=str(target),sha256=digest,zip_member=entry.filename))
                    asset['path']=str(target)
        if owner._sha256(archive) != archive_ref['sha256']:
            raise ValueError('source_archive_changed_during_restore')
    data['source_archive_ref']=archive_ref
    data['source_data_member']=data_member
    data_path=output/'publication-data.json'
    desk.write_new(data_path,data)
    receipt=dict(schema='self-media.publication-archive-migration.v1',status='restored_metadata_pending_checks',
        archive_ref=archive_ref,data_member=data_member,data_path=str(data_path),data_sha256=owner._sha256(data_path),
        assets=mapping,disk_preflight=disk,original_archive_unchanged=True,
        media_reencoded=False,human_approved=False,published=False,rebuild_verified=False)
    owner._write_json_atomic(output/'migration-receipt.json',receipt)
    return receipt


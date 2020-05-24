#!/usr/bin/env python3

import subprocess
import tempfile
import argparse
import shlex
import os
import os.path
import sys
import shutil
import logging
import logging.handlers
import platform
import json

import requests


LOG_LEVEL = logging.INFO

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger("telegram")
log.setLevel(LOG_LEVEL)


def parse_args():
    default_dir = os.getcwd()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, metavar="arg", default=default_dir,
                        help="directory where to put generated deb package")
    parser.add_argument("--version", type=str, metavar="arg", required=False,
                        help="version to download")
    args = parser.parse_args()

    return args


def exec_cmd(cmd, shell=False):
    try:
        if shell:
            subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        else:
            args = shlex.split(cmd)
            subprocess.check_output(args, shell=False, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        log.error("'{cmd}' failed, exit status={status}, output='{output}'".
                  format(cmd=cmd, status=exc.returncode, output=exc.output.decode("utf-8").strip()))
        sys.exit(-1)


def find_utils(utils):
    path = {}

    for u in utils:
        p = shutil.which(u)
        if p is None:
            log.error("utility {} was not found in path(s) specified in $PATH".format(u))
            sys.exit(-1)
        path[u] = p

    return path


def get_latest_github_release_url(owner, project, version):
    if platform.machine() != "x86_64":
        raise Exception("Architecture {arch} unsupported by {project} project".format(
            arch=platform.machine(), project=project))

    if version is not None and len(version) > 0 and version[0] != 'v':
        version = "v" + version

    url = "https://api.github.com/repos/{owner}/{project}/releases".format(owner=owner, project=project)

    r = requests.get(url)
    if r.status_code and r.status_code > 300:
        raise Exception("failed to fetch url '{}', status code {}".format(url, r.status_code))

    js = json.loads(r.content)

    for e in js:
        if version is None:
            version = e["tag_name"]

        if version == e["tag_name"]:
            for asset in e["assets"]:
                if "label" in asset and asset["label"] == "Linux 64 bit: Binary":
                    return (asset["browser_download_url"], version)

    raise Exception("No precompiled binaries found for Linux x86_64 target.")


def create_deb_package(args, root):
    utils = find_utils(["wget", "fpm", "tar"])

    dl_dir = os.path.join(root, "download", "tdesktop")
    install_base_dir = os.path.join(root, "install")
    install_dir = os.path.join(install_base_dir, "opt", "telegram")
    work_dir = os.path.dirname(os.path.realpath(__file__))

    os.makedirs(dl_dir, exist_ok=True)

    version = args.version if args.version else None
    url, version = get_latest_github_release_url("telegramdesktop", "tdesktop", version)
    version = version[1:] if version[0] == 'v' else version

    tmp_archive = tempfile.mktemp()
    cmd = "{wget} -q {url} -P {dl_dir} -O {archive}".format(
        wget=utils["wget"], url=url, dl_dir=dl_dir, archive=tmp_archive)
    log.info("downloading precompiled Telegram package '{}'".format(url))
    exec_cmd(cmd)

    cmd = "{tar} xfJ {fn} -C {target_dir}".format(tar=utils["tar"], fn=tmp_archive, target_dir=dl_dir)
    exec_cmd(cmd)

    os.unlink(tmp_archive)

    log.debug("copying '{src}' to '{dst}'".format(src=os.path.join(dl_dir, "Telegram"), dst=install_dir))
    shutil.copytree(os.path.join(dl_dir, "Telegram"), install_dir)

    os.chdir(install_dir)

    shutil.move("Telegram", "telegram")

    log.debug("copying '{src}' to '{dst}'".format(src=os.path.join(work_dir, "files", "usr"), dst=install_base_dir))
    shutil.copytree(os.path.join(work_dir, "files", "usr"), os.path.join(install_base_dir, "usr"))

    shutil.copy(os.path.join(work_dir, "files", "opt", "telegram", "Telegram"), install_dir)
    shutil.copy(os.path.join(work_dir, "files", "opt", "telegram", "telegram.svg"), install_dir)

    if not os.path.exists(args.dir):
        os.makedirs(args.dir, exist_ok=True)

    os.chdir(args.dir)

    log.info("building deb package")
    cmd = "{fpm} " \
          "--input-type dir " \
          "--output-type deb " \
          "--name telegram " \
          "--version {version} " \
          "--deb-compression xz " \
          "--description \"Telegram Desktop\" " \
          "--maintainer \"Konstantin Sorokin <kvs@sigterm.ru>\" " \
          "--chdir {base_dir}".format(fpm=utils["fpm"], version=version, base_dir=install_base_dir)
    exec_cmd(cmd, True)

    log.info("deb package created in the '{}' directory".format(args.dir))

    shutil.rmtree(root)


def main():
    args = parse_args()

    tmp_dir = tempfile.mkdtemp()
    log.debug("temporary work directory is '{}'".format(tmp_dir))

    create_deb_package(args, tmp_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error(exc)
        sys.exit(-1)

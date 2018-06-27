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
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=str, metavar="arg", default="/tmp/",
                        help="directory where to put deb and rpm packages")
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


def get_latest_github_release_url(owner, project):
    if platform.machine() != "x86_64":
        raise Exception("Architecture {arch} unsupported by {project} project".format(arch=platform.machine(), project=project))

    url = "https://api.github.com/repos/{owner}/{project}/releases/latest".format(owner=owner, project=project)

    r = requests.get(url)
    if r.status_code and r.status_code > 300:
        raise Exception("failed to fetch url '{}', status code {}".format(url, r.status_code))

    js = json.loads(r.text)
    if "assets" not in js:
        raise Exception("No precompiled assets found")

    if "tag_name" not in js:
        raise Exception("Couldn't find version info")

    version = js["tag_name"]
    if version[0] == 'v':
        version = version[1:]

    for asset in js["assets"]:
        if "label" in asset and asset["label"] == "Linux 64 bit: Binary":
            return (asset["browser_download_url"], version)

    raise Exception("No precompiled binaries found for Linux x86_64")


def create_deb_package(args, root):
    utils = find_utils(["wget", "fpm", "tar"])

    dl_dir = os.path.join(root, "download", "tdesktop")
    install_base_dir = os.path.join(root, "install")
    install_dir = os.path.join(install_base_dir, "opt", "telegram")
    work_dir = os.path.dirname(os.path.realpath(__file__))

    os.makedirs(dl_dir, exist_ok=True)

    url, version = get_latest_github_release_url("telegramdesktop", "tdesktop")

    tmp_archive = tempfile.mktemp()
    cmd = "{wget} -q {url} -P {dl_dir} -O {archive}".format(wget=utils["wget"], url=url, dl_dir=dl_dir, archive=tmp_archive)
    log.info("downloading precompiled package '{}' to '{}' file".format(url, tmp_archive))
    exec_cmd(cmd)

    cmd = "{tar} xfJ {fn} -C {target_dir}".format(tar=utils["tar"], fn=tmp_archive, target_dir=dl_dir)
    exec_cmd(cmd)

    os.unlink(tmp_archive)

    log.info("copying '{src}' to '{dst}'".format(src=os.path.join(dl_dir, "Telegram"), dst=install_dir))
    shutil.copytree(os.path.join(dl_dir, "Telegram"), install_dir)

    os.chdir(install_dir)

    shutil.move("Telegram", "telegram")

    log.info("copying '{src}' to '{dst}'".format(src=os.path.join(work_dir, "files", "usr"), dst=install_base_dir))
    shutil.copytree(os.path.join(work_dir, "files", "usr"), os.path.join(install_base_dir, "usr"))

    shutil.copy(os.path.join(work_dir, "files", "opt", "telegram", "Telegram"), install_dir)
    shutil.copy(os.path.join(work_dir, "files", "opt", "telegram", "telegram.svg"), install_dir)

    if not os.path.exists(args.result_dir):
        os.makedirs(args.result_dir, exist_ok=True)

    os.chdir(args.result_dir)

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

    log.info("package(s) created in {}".format(args.result_dir))

    shutil.rmtree(root)


def main():
    args = parse_args()

    tmp_dir = tempfile.mkdtemp()
    log.info("temporary work directory is '{}'".format(tmp_dir))

    create_deb_package(args, tmp_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error(exc)
        sys.exit(-1)

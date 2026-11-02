"""관리용 CLI. 예: python -m app.cli create-device --id freezer-01 / create-user --username kim --role admin"""
import argparse
import getpass
import re

from app.services import auth, devices


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-device", help="장치 등록/키 교체 (키는 한 번만 출력)")
    c.add_argument("--id", required=True)
    u = sub.add_parser("create-user", help="사용자 생성/비밀번호 교체 (비밀번호는 프롬프트로 입력)")
    u.add_argument("--username", required=True)
    u.add_argument("--role", choices=auth.ROLES, default="viewer")
    a = p.parse_args()
    if a.cmd == "create-user":
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", a.username):
            p.error("username은 영문/숫자/._- 1~64자")
        pw = getpass.getpass("비밀번호: ")
        if pw != getpass.getpass("비밀번호 확인: "):
            p.error("비밀번호가 일치하지 않습니다")
        try:
            auth.create_user(a.username, pw, a.role)
        except ValueError as e:
            p.error(str(e))
        print(f"사용자 저장됨: {a.username} ({a.role})")
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", a.id):
        p.error("id는 영문/숫자/_/- 1~64자")
    print(f"device_id: {a.id}\nAPI key  : {devices.create_device(a.id)}\n(이 키는 다시 볼 수 없습니다. 펌웨어 config.h에 넣으세요)")


if __name__ == "__main__":
    main()

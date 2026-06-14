from __future__ import annotations

import argparse
from database.store import create_api_key_for_user, create_user, init_db


def main():
    p = argparse.ArgumentParser(description="Create Trading Desk OS API user/key")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--plan", default="free", choices=["free", "starter", "pro", "desk"])
    p.add_argument("--credits", type=int, default=None)
    p.add_argument("--label", default="default")
    args = p.parse_args()
    init_db()
    create_user(args.email, args.name, args.plan, args.credits)
    result = create_api_key_for_user(args.email, args.label)
    print("API KEY - copy now, it is only shown once:")
    print(result["api_key"])


if __name__ == "__main__":
    main()

import psycopg2
import sys

from .local_settings import config


def main():
    if len(sys.argv) < 2:
        tool_name = sys.argv[0][sys.argv[0].rfind("/")+1:]
        print((
            "usage: {} [-n <count>] <dnnnnnn | DOI>".format(tool_name) + "\n"
        ))

    try:
       conn = psycopg2.connect(**config['citation-database'])
       cursor = conn.cursor()
    finally:
       conn.close()


if __name__ == "__main__":
    main()

import psycopg2
import sys

from .cache import clean_cache
from .configure import configure
from .local_settings import config


def on_crash(exctype, value, traceback):
    if DEBUG:
        sys.__excepthook__(exctype, value, traceback)
    else:
        print(f"{exctype.__name__}: {value}")


sys.excepthook = on_crash


def main():
    tool_name = sys.argv[0][sys.argv[0].rfind("/")+1:]
    if len(sys.argv[1:]) == 0 or sys.argv[1] == "--help":
        print((
            f"usage: {tool_name} configure <file>\n"
            f"usage: {tool_name} <DOI_GROUP> [options...]\n"
            f"usage: {tool_name} --help\n"
            f"usage: {tool_name} --show-doi-groups\n"
            "\n"
            "required:\n"
            "file            configure the tool from entries in <file>\n"
            "                file 'local_settings.py' is created\n"
            "DOI_GROUP       doi group for which to get citation statistics\n"
            "                (see --show-doi-groups)\n"
            "\n"
            "options:\n"
            "-d <DOI_DATA>   get citation data for a single DOI only\n"
            "                DOI_DATA is a delimited string (see -s) "
            "containing three items:\n"
            "                - the DOI\n"
            "                - the publisher of the DOI\n"
            "                - the asset type\n"
            "-k              keep the json files from the APIs (default is to "
            "remove them)\n"
            "--no-works      don't collect information about the citing "
            "works\n"
            "--only-services <SERVICES>\n"
            "                comma-delimited list of the only services to "
            "query (default is\n"
            "                to query all known services)\n"
            "--no-services <SERVICES>\n"
            "                comma-delimited list of services to ignore\n"
            "-s DELIMITER    delimiter string for DOI_DATA (default is a "
            "semicolon)\n"
        ))
        sys.exit(1)

    global DEBUG
    DEBUG = False
    args = sys.argv[1:]
    if args[0] == "configure":
        del args[0]
        if len(args) == 0:
            raise ValueError("missing input settings file name")

        configure(args[0])
        sys.exit(0)

    if len(config) == 0:
        raise ValueError((
                f"missing configuration - run {tool_name} in 'configure' "
                "mode"))

    if args[0] == "--show-doi-groups":
        x = 0
        for key in config['doi-groups'].keys():
            x = max(x, len(key))

        x += 2
        for key, value in config['doi-groups'].items():
            print(f"{key:>{x}}: ({value['publisher']})")

        sys.exit(0)

    clean_cache()
    doi_group = args[0]
    if doi_group not in config['doi-groups']:
        raise ValueError(f"'{doi_group}' is not a valid doi group")

    try:
        db = config['citation-database']
        conn = psycopg2.connect(user=db['user'], password=db['password'],
                                host=db['host'], dbname=db['dbname'],
                                connect_timeout=30)
        cursor = conn.cursor()
        cursor.execute((
                f"create table if not exists {db['schemaname']}."
                f"{config['doi-groups'][doi_group]['db-table']} (like "
                f"{db['schemaname']}.template_data_citations including all)"))
        conn.commit()
    except Exception as err:
        print(f"Database error: '{err}'")
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    main()

import os
import psycopg2
import sys

from datetime import datetime

from .cache import clean_cache
from .configure import configure
from .doi_list import get_doi_list
from .local_settings import config
from .crossref import do_query as query_crossref
from .scopus import do_query as query_scopus
from .wos import do_query as query_wos


def on_crash(exctype, value, traceback):
    if DEBUG:
        sys.__excepthook__(exctype, value, traceback)
    else:
        print(f"{exctype.__name__}: {value}")


sys.excepthook = on_crash


def parse_args(args):
    if args[0] not in config['doi-groups']:
        raise ValueError(f"'{args[0]}' is not a valid doi group")

    settings = {'doi_group': args[0], 'keep_json': False, 'delimiter': ";",
                'services': []}
    n = 1
    while n < len(args):
        if args[n] == "-d":
            n += 1
            doi_data = args[n]
        elif args[n] == "-s":
            n += 1
            settings['delimiter'] = args[n]
        elif args[n] == "--only-services":
            n += 1
            for service in args[n].split(","):
                service = service.strip()
                if service in config['services'].keys():
                    settings['services'].append(service)
                else:
                    raise ValueError(f"'{service}' is not a valid service")

        elif args[n] == "--no-services":
            n += 1
            no_services = [s for s in args[n].split(",")]
        elif args[n] == "-k":
            pass
        elif args[n] == "--no-works":
            pass

        n += 1

    if len(settings['services']) == 0:
        settings['services'] = [s for s in config['services'].keys()]

    if 'no_services' in locals():
        for service in no_services:
            try:
                del settings['services'][settings['services'].index(service)]
            except Exception:
                raise ValueError(f"'{service}' is not a valid service")

    if 'doi_data' in locals():
        parts = doi_data.split(settings['delimiter'])
        if len(parts) == 3:
            settings['doi_list'] = [tuple(parts)]
        else:
            raise ValueError(
                    f"'{doi_data}' not in proper format (delimiter is "
                    f"'{settings['delimiter']}')")

    return settings


def query_service(service, **kwargs):
    kwargs['output'].write(f"Querying '{service}' ...\n")
    if service == "crossref":
        query_crossref(**kwargs)
    elif service == "scopus":
        query_scopus(**kwargs)
    elif service == "wos":
        query_wos(**kwargs)

    kwargs['output'].write(f"... done querying '{service}'.\n")


def main():
    tool_name = sys.argv[0][sys.argv[0].rfind("/")+1:]
    if len(sys.argv[1:]) == 0 or sys.argv[1] == "--help":
        print((
            f"usage: {tool_name} configure SETTINGS_FILE\n"
            f"usage: {tool_name} DOI_GROUP [options...]\n"
            f"usage: {tool_name} --help\n"
            f"usage: {tool_name} --show-doi-groups\n"
            "\n"
            "required:\n"
            "SETTINGS_FILE   source file for configuring the tool (see the "
            "template\n"
            "                'settings.txt')\n"
            "DOI_GROUP       doi group for which to get citation statistics\n"
            "                (see --show-doi-groups)\n"
            "\n"
            "options:\n"
            "-d DOI_DATA     get citation data for a single DOI only\n"
            "                DOI_DATA is a delimited string (see -s) "
            "containing three items:\n"
            "                - the DOI\n"
            "                - the publisher of the DOI\n"
            "                - the asset type\n"
            "-k              keep the json files from the APIs (default is to "
            "remove them)\n"
            "--no-works      don't collect information about the citing "
            "works\n"
            "--only-services SERVICES\n"
            "                comma-delimited list of the only services to "
            "query (default is\n"
            "                to query all known services)\n"
            "--no-services SERVICES\n"
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
    settings = parse_args(args)
    print(settings)
    output_file = os.path.join(
            config['temporary-directory-path'],
            "output." + datetime.now().strftime("%Y%m%d%H%M"))
    with open(output_file, "w") as settings['output']:
        print(f"Output file is {output_file}")
        try:
            db = config['citation-database']
            conn = psycopg2.connect(user=db['user'], password=db['password'],
                                    host=db['host'], dbname=db['dbname'],
                                    connect_timeout=30)
            cursor = conn.cursor()
            cursor.execute((
                    "create table if not exists {}.{} (like {}."
                    "template_data_citations including all)").format(
                    db['schemaname'],
                    config['doi-groups'][settings['doi_group']]['db-table'],
                    db['schemaname']))
            conn.commit()
        except Exception as err:
            print(f"Database error: '{err}'")
        finally:
            if 'conn' in locals():
                conn.close()

        if 'doi_list' not in settings:
            settings['doi_list'] = (
                    get_doi_list(settings['doi_group'],
                                 output=settings['output']))

        print(settings['doi_list'])
        for service in settings['services']:
            query_service(service, doi_list=settings['doi_list'],
                          output=settings['output'])


if __name__ == "__main__":
    main()

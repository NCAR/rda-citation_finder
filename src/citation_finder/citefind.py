import importlib
import io
import os
import pkg_resources
import sys

from datetime import datetime
from libpkg.unixutils import sendmail
from pathlib import Path

from .cache import clean_cache
from .configure import configure
from .doi_list import get_doi_list
from .integrity import run_integrity_checks
from .local_settings import config
from .utils import db_connect


def on_crash(exctype, value, traceback):
    if DEBUG:
        sys.__excepthook__(exctype, value, traceback)
    else:
        print(f"{exctype.__name__}: {value}")


sys.excepthook = on_crash


def parse_args(args):
    if args[0] not in config['doi-groups']:
        raise ValueError(f"'{args[0]}' is not a valid doi group")

    settings = {'doi-group': args[0], 'keep-json': False, 'no-works': False,
                'delimiter': ";", 'services': []}
    n = 1
    while n < len(args):
        if args[n] == "-d":
            n += 1
            doi_data = args[n]
        elif args[n] == "-s":
            n += 1
            settings['delimiter'] = args[n]
        elif args[n] == "-t":
            global DEBUG
            DEBUG = True
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
            settings['keep-json'] = True
        elif args[n] == "--no-works":
            settings['no-works'] = True

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
            settings['doi-list'] = [tuple([e.strip() for e in parts])]
        else:
            raise ValueError(
                    f"'{doi_data}' not in proper format (delimiter is "
                    f"'{settings['delimiter']}')")

    return settings


def query_service(module, **kwargs):
    service = getattr(module, '__name__').split(".")[-1]
    kwargs['output'].write(f"Querying '{service}' ...\n")
    find_citations = getattr(module, 'find_citations')
    find_citations(**kwargs)
    kwargs['output'].write(f"... done querying '{service}'.\n")


def main():
    tool_name = sys.argv[0][sys.argv[0].rfind("/")+1:]
    if len(sys.argv[1:]) == 0 or sys.argv[1] == "--help":
        print((
            f"usage: {tool_name} template SETTINGS_FILE\n"
            f"usage: {tool_name} configure SETTINGS_FILE\n"
            f"usage: {tool_name} DOI_GROUP [options...]\n"
            f"usage: {tool_name} --help\n"
            f"usage: {tool_name} --show-doi-groups\n"
            "\n"
            "required:\n"
            "SETTINGS_FILE   for 'template': makes a copy of the settings "
            "template in \n"
            "                  the current directory, which must be edited to "
            "specify the\n"
            "                  various settings values\n"
            "                for 'configure': uses the values in "
            "SETTINGS_FILE to configure\n"
            "                  the tool\n"
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
            "-k              keep the json files from the APIs - useful for "
            " testing\n"
            "                (default is to remove them)\n"
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
            "-t              turn on traceback for abnormal exit\n"
        ))
        sys.exit(1)

    global DEBUG
    DEBUG = False
    args = sys.argv[1:]
    if args[0] == "template":
        del args[0]
        if len(args) == 0:
            raise ValueError("missing output settings file name")

        template_path = "/".join(["templates", "settings.txt"])
        template = pkg_resources.resource_string(__name__, template_path)
        with open(args[0], "w") as f:
            f.write(template.decode("utf-8"))

        sys.exit(0)

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
    mail_message = io.StringIO()
    output_file = os.path.join(
            config['temporary-directory-path'],
            "output." + datetime.now().strftime("%Y%m%d%H%M"))
    with open(output_file, "w") as output:
        msg = f"Output file is {output_file}"
        mail_message.write(f"{msg}\n")
        print(msg)
        conn, err = db_connect()
        if conn is None:
            err = f"Database connection error: '{err}'"
            output.write(f"{err}\n")
            raise RuntimeError(err)

        try:
            cursor = conn.cursor()
            schemaname = config['citation-database']['schemaname']
            cursor.execute((
                    "create table if not exists {}.{} (like {}."
                    "template_data_citations including all)").format(
                    schemaname,
                    config['doi-groups'][settings['doi-group']]['db-table'],
                    schemaname))
            conn.commit()
            conn.close()
            if 'doi-list' not in settings:
                settings['doi-list'] = (
                        get_doi_list(settings['doi-group'],
                                     output=output))

            print(settings['doi-list'])
            print(settings['services'])
            for service in settings['services']:
                mail_message.write(f"Querying '{service}'.\n")
                module = importlib.import_module(
                        "." + service, package=__package__)
                query_service(module, doi_group=settings['doi-group'],
                              doi_list=settings['doi-list'],
                              output=output,
                              no_works=settings['no-works'])

            run_integrity_checks(schemaname=schemaname,
                                 mail_message=mail_message)
        except Exception as err:
            err = f"An error occured: '{err}'"
            output.write(f"{err}\n")
            raise RuntimeError(err)
        finally:
            if not settings['keep-json']:
                for file in Path(
                        config['temporary-directory-path']).glob("*.json"):
                    file.unlink()

            try:
                sendmail(["dattore@ucar.edu"], "dattore@ucar.edu",
                         f"citefind cron for {settings['doi-group']}",
                         mail_message.getvalue(), host=config['mail']['host'],
                         port=int(config['mail']['port']))
            except Exception as err:
                err = (f"***SENDMAIL error: '{err}' using host/port: "
                       f"'{config['mail']['host']}/{config['mail']['port']}'")
                output.write(f"{err}\n")
                raise RuntimeError(err)


if __name__ == "__main__":
    main()

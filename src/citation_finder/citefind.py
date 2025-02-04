import sys


from .configure import configure


def main():
    if len(sys.argv[1:]) == 0 or sys.argv[1] == "--help":
        tool_name = sys.argv[0][sys.argv[0].rfind("/")+1:]
        print((
            "usage: {} configure <file>".format(tool_name) + "\n"
            "usage: {} <DOI_GROUP> [options...]".format(tool_name) + "\n"
            "usage: {} --help".format(tool_name) + "\n"
            "usage: {} --show-doi-groups".format(tool_name) + "\n"
            "\n"
            "required\n"
            "file            configure the tool from entries in <file>\n"
            "                file 'local_settings.py' is created\n"
            "DOI_GROUP       doi group for which to get citation statistics\n"
            "                (see --show-doi-groups)\n"
            "\n"
            "options\n"
            "-d <DOI_DATA>   get citation data for a single DOI only\n"
            "                DOI_DATA is a delimited string (see -s) containing three items:\n"
            "                - the DOI\n"
            "                - the publisher of the DOI\n"
            "                - the asset type\n"
            "-k              keep the json files from the APIs (default is to remove them)\n"
            "--no-works      don't collect information about the citing works\n"
            "--only-services <SERVICES>\n"
            "                comma-delimited list of the only services to query (default is\n"
            "                to query all known services)\n"
            "--no-services <SERVICES>\n"
            "                comma-delimited list of services to ignore\n"
            "-s DELIMITER    delimiter string for DOI_DATA (default is a semicolon)\n"
        ))
        sys.exit(1)

    args = sys.argv[1:]
    if args[0] == "configure":
        configure(args[1])


if __name__ == "__main__":
    main()

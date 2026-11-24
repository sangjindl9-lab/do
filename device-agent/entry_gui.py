import sys

from gat_agent.cli import main

sys.exit(main(sys.argv[1:] or ["gui"]))

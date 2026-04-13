import logging
import sys

TRACE_LEVEL = 5
TRACE2_LEVEL = 1


def consume_verbosity_flags() -> int:
    """Parse and remove -v/-vv/-vvv from sys.argv for Hydra/argparse compatibility."""
    if not sys.argv:
        return 0

    verbosity = 0
    filtered_argv = [sys.argv[0]]
    for arg in sys.argv[1:]:
        if arg == "-v":
            verbosity = max(verbosity, 1)
            continue
        if arg == "-vv":
            verbosity = max(verbosity, 2)
            continue
        if arg == "-vvv":
            verbosity = max(verbosity, 3)
            continue
        filtered_argv.append(arg)

    sys.argv = filtered_argv
    return verbosity


def configure_logging(verbosity: int = 0) -> int:
    """Configure root logger by verbosity: default / -v / -vv / -vvv."""
    verbosity = max(0, min(3, int(verbosity)))

    logging.addLevelName(TRACE_LEVEL, "TRACE")
    logging.addLevelName(TRACE2_LEVEL, "TRACE2")

    level_by_verbosity = {
        0: logging.INFO,
        1: logging.DEBUG,
        2: TRACE_LEVEL,
        3: TRACE2_LEVEL,
    }
    selected_level = level_by_verbosity[verbosity]

    logging.basicConfig(
        level=selected_level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    return selected_level

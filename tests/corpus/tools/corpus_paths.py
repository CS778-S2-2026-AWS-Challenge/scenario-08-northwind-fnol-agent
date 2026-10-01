"""Where the corpus folders are in the repository.

The tools sit in tests/corpus/tools/ next to tests/corpus/controlled/, which holds the specs, the
committed manifests and, once fetched, the packs. Tools run in module mode from the repository
root (python -m tests.corpus.tools.<tool>), so a tool that starts another one uses REPO_ROOT.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
CONTROLLED = os.path.normpath(os.path.join(HERE, '..', 'controlled'))
CORPUS_V1 = os.path.join(CONTROLLED, 'v1')
SAMPLES = os.path.join(CONTROLLED, 'samples-0.2')
SPECS_V1 = os.path.join(CONTROLLED, 'specs', 'v1')
WORK = os.path.normpath(os.path.join(HERE, '..', 'work'))

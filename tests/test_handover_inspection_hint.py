"""An inspection failure on handover completion names the transfer acknowledgment and still blocks."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from partyline import handover_jobs


class InspectionFailureHintTest(unittest.TestCase):
    def test_failed_inspection_names_transfer_and_stays_a_409(self):
        runtime = SimpleNamespace(live={"worker-att": SimpleNamespace(proc=SimpleNamespace(pid=1234))})
        with patch.object(handover_jobs, "process_snapshot", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                handover_jobs.live_jobs(runtime, "worker-att")

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('live_jobs="transfer"', caught.exception.detail)
        self.assertIn("not waived", caught.exception.detail)

"""Checks for the engine's ports and facts."""
import inspect
import unittest
from dataclasses import FrozenInstanceError, MISSING, fields
from datetime import datetime, timedelta

from baton.domain.capabilities import Capabilities
from baton.domain.errors import BatonError
from baton.domain import errors
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock, SystemClock
from baton.ports.store import RecordStore


class PortsTests(unittest.TestCase):
    def test_store_signatures(self):
        public = lambda cls: {name for name, value in inspect.getmembers(cls)
                              if not name.startswith("_") and inspect.isfunction(value)}
        self.assertEqual(public(RecordStore), public(Ledger))
        for name in public(RecordStore):
            self.assertEqual(inspect.signature(getattr(RecordStore, name)),
                             inspect.signature(getattr(Ledger, name)))
        store = Ledger(":memory:")
        self.addCleanup(store.close)
        self.assertIsInstance(store, RecordStore)

    def test_fixed_clock(self):
        clock = FixedClock("2026-01-01T00:00:00+00:00")
        self.assertEqual(clock.now(), clock.value)
        clock.value = "2026-01-02T00:00:00+00:00"
        self.assertEqual(clock.now(), "2026-01-02T00:00:00+00:00")

    def test_system_clock(self):
        before = datetime.fromisoformat(SystemClock().now())
        self.assertEqual(before.utcoffset(), timedelta(0))
        self.assertLessEqual(before, datetime.fromisoformat(SystemClock().now()))

    def test_capabilities_require_every_field(self):
        values = {field.name: False for field in fields(Capabilities)}
        for field in fields(Capabilities):
            self.assertIs(field.default, MISSING)
            self.assertIs(field.default_factory, MISSING)
            with self.assertRaises(TypeError):
                Capabilities(**{key: value for key, value in values.items() if key != field.name})
        facts = Capabilities(**values)
        with self.assertRaises(FrozenInstanceError):
            facts.can_cut = True

    def test_errors_share_base(self):
        for value in vars(errors).values():
            if inspect.isclass(value) and issubclass(value, Exception):
                self.assertTrue(issubclass(value, BatonError))

from __future__ import annotations

import os

import semantic_provider


def test_health_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(semantic_provider, '_STATE', tmp_path / 'health.json')
    info = semantic_provider.health()
    assert 'primary' in info
    assert 'circuit_open' in info


def test_circuit_opens_after_two_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(semantic_provider, '_STATE', tmp_path / 'health.json')
    semantic_provider._mark_failure('local', 'x')
    assert semantic_provider._circuit_open() is False
    semantic_provider._mark_failure('local', 'y')
    assert semantic_provider._circuit_open() is True

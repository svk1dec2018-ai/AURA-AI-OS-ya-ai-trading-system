from aura.evolution.core import PopulationEvolution
from aura.research.autonomous_strategy_lab import autonomous_strategy_gene_specs
from aura.research.strategy_mutation import mutate_autonomous_genome


def test_autonomous_mutation_creates_distinct_child_without_risk_genes() -> None:
    evolution = PopulationEvolution(
        autonomous_strategy_gene_specs(),
        family="autonomous_strategy_dsl.v1",
    )
    parent = evolution.random_genome()
    child = mutate_autonomous_genome(parent, seed=42)
    assert child.content_hash != parent.content_hash
    assert child.generation == parent.generation + 1
    assert child.parents == (parent.genome_id,)
    forbidden = {
        "risk_per_trade",
        "max_daily_loss",
        "max_drawdown",
        "kill_switch",
        "broker_permission",
        "live_approval",
    }
    assert not forbidden.intersection(child.parameters)
    assert set(child.parameters) == {item.name for item in autonomous_strategy_gene_specs()}

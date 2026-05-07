"""Genetic algorithm for creature evolution — replaces Gemini's decide_evolution call."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

_STAT_NAMES = ["health", "attack", "defense", "speed"]
_MAX_POOL_SIZE = 20
_EVOLUTION_BONUS = 10   # matches validators.EVOLUTION_BONUS


# ---------------------------------------------------------------------------
# Gene representation
# ---------------------------------------------------------------------------


@dataclass
class Gene:
    health:  float
    attack:  float
    defense: float
    speed:   float
    fitness: float = field(default=0.0, compare=False)

    def to_stats(self, tier: str) -> dict[str, int]:
        """Denormalize normalized ratios to integer stats that satisfy tier constraints."""
        from backend.graphs.nodes.validators import TIER_BUDGETS
        budget, max_single, _ = TIER_BUDGETS[tier]

        sorted_by_ratio = sorted(_STAT_NAMES, key=lambda s: getattr(self, s), reverse=True)
        result = {
            s: max(1, min(int(getattr(self, s) * budget), max_single))
            for s in _STAT_NAMES
        }

        remainder = budget - sum(result.values())
        if remainder > 0:
            for s in sorted_by_ratio:
                if remainder <= 0:
                    break
                headroom = max_single - result[s]
                add = min(remainder, headroom)
                result[s] += add
                remainder -= add
        elif remainder < 0:
            for s in reversed(sorted_by_ratio):
                if remainder >= 0:
                    break
                can_remove = result[s] - 1
                remove = min(-remainder, can_remove)
                result[s] -= remove
                remainder += remove

        return result

    def _renormalize(self) -> None:
        total = self.health + self.attack + self.defense + self.speed
        if total > 0:
            self.health  /= total
            self.attack  /= total
            self.defense /= total
            self.speed   /= total


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------


def compute_fitness(analysis: dict[str, Any], max_turns: int = 30) -> float:
    win_rate  = float(analysis.get("win_rate", 0.0))
    avg_turns = float(analysis.get("avg_turns", max_turns))
    # High win rate good (70%) + winning quickly good (30%)
    efficiency = 1.0 - min(avg_turns / max_turns, 1.0)
    return round(win_rate * 0.70 + efficiency * 0.30, 4)


# ---------------------------------------------------------------------------
# Genetic operators
# ---------------------------------------------------------------------------


def crossbreed(gene_a: Gene, gene_b: Gene, rng: random.Random) -> Gene:
    """Uniform crossover — each stat independently picked from either parent."""
    child = Gene(
        health  = gene_a.health  if rng.random() < 0.5 else gene_b.health,
        attack  = gene_a.attack  if rng.random() < 0.5 else gene_b.attack,
        defense = gene_a.defense if rng.random() < 0.5 else gene_b.defense,
        speed   = gene_a.speed   if rng.random() < 0.5 else gene_b.speed,
    )
    child._renormalize()
    return child


def mutate(gene: Gene, rng: random.Random, sigma: float = 0.05) -> Gene:
    """Gaussian noise on 1–2 stats, then renormalize."""
    child = Gene(
        health=gene.health, attack=gene.attack,
        defense=gene.defense, speed=gene.speed,
    )
    n_mutate = rng.randint(1, 2)
    for s in rng.sample(_STAT_NAMES, n_mutate):
        noise = rng.gauss(0.0, sigma)
        setattr(child, s, max(0.01, getattr(child, s) + noise))
    child._renormalize()
    return child


# ---------------------------------------------------------------------------
# Gene pool persistence
# ---------------------------------------------------------------------------


def _seed_pool(tier: str) -> list[Gene]:
    from backend.graphs.nodes.stat_generator import ARCHETYPE_BIAS
    return [
        Gene(health=b["health"], attack=b["attack"], defense=b["defense"], speed=b["speed"],
             fitness=0.5)
        for b in ARCHETYPE_BIAS.values()
    ]


def _update_pool(pool: list[Gene], new_gene: Gene, max_size: int = _MAX_POOL_SIZE) -> list[Gene]:
    pool = pool + [new_gene]
    pool.sort(key=lambda g: g.fitness, reverse=True)
    return pool[:max_size]


def load_gene_pool(path: Path, tier: str) -> list[Gene]:
    try:
        if path.exists():
            data = json.loads(path.read_text())
            tier_data = data.get(tier, [])
            if tier_data:
                return [
                    Gene(
                        health=float(d["health"]),
                        attack=float(d["attack"]),
                        defense=float(d["defense"]),
                        speed=float(d["speed"]),
                        fitness=float(d.get("fitness", 0.0)),
                    )
                    for d in tier_data
                ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("genetic | failed to load gene pool from {}: {}", path, exc)
    return _seed_pool(tier)


def save_gene_pool(path: Path, tier: str, pool: list[Gene]) -> None:
    try:
        existing: dict = {}
        if path.exists():
            existing = json.loads(path.read_text())
        existing[tier] = [
            {
                "health":  round(g.health, 6),
                "attack":  round(g.attack, 6),
                "defense": round(g.defense, 6),
                "speed":   round(g.speed, 6),
                "fitness": round(g.fitness, 4),
            }
            for g in pool
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2))
    except Exception as exc:  # noqa: BLE001
        logger.warning("genetic | failed to save gene pool to {}: {}", path, exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def genetic_decide_evolution(
    parent_creature: dict[str, Any],
    analysis: dict[str, Any],
    gene_pool_path: Path | None = None,
) -> dict[str, Any]:
    """Use a genetic algorithm to decide which stats to boost on evolution."""
    from backend.graphs.nodes.validators import TIER_BUDGETS

    tier = parent_creature["tier"]
    budget, max_single, _ = TIER_BUDGETS[tier]

    if gene_pool_path is None:
        from backend.core.config import get_settings
        gene_pool_path = get_settings().data_dir / "gene_pool.json"

    rng = random.Random(
        f"{parent_creature['id']}:ga:{parent_creature.get('generation', 0)}"
    )

    from backend.core.config import get_settings
    _test_mode = get_settings().app_env == "test"

    # --- Build parent gene ---
    parent_stats: dict[str, int] = parent_creature["stats"]
    parent_gene = Gene(
        health  = parent_stats["health"]  / budget,
        attack  = parent_stats["attack"]  / budget,
        defense = parent_stats["defense"] / budget,
        speed   = parent_stats["speed"]   / budget,
        fitness = compute_fitness(analysis),
    )

    # In test mode: always use fresh seeded pool (deterministic, no disk I/O)
    if _test_mode:
        pool = _seed_pool(tier)
    else:
        pool = load_gene_pool(gene_pool_path, tier)

    # --- Update pool ---
    pool = _update_pool(pool, parent_gene)

    # --- Breed child ---
    if len(pool) >= 2:
        top_a, top_b = sorted(pool, key=lambda g: g.fitness, reverse=True)[:2]
        child_gene = crossbreed(top_a, top_b, rng)
    else:
        child_gene = Gene(
            health=parent_gene.health, attack=parent_gene.attack,
            defense=parent_gene.defense, speed=parent_gene.speed,
        )

    child_gene = mutate(child_gene, rng)
    child_stats = child_gene.to_stats(tier)

    # --- Compute stat_boosts (positive deltas only, cap total to EVOLUTION_BONUS) ---
    raw_boosts: dict[str, int] = {}
    for stat in _STAT_NAMES:
        delta = child_stats[stat] - parent_stats[stat]
        if delta > 0:
            max_allowed = max_single - parent_stats[stat]
            if max_allowed > 0:
                raw_boosts[stat] = min(delta, max_allowed)

    total_boost = sum(raw_boosts.values())
    if total_boost > _EVOLUTION_BONUS:
        # Scale down, keeping highest boosts first
        stat_boosts: dict[str, int] = {}
        remaining = _EVOLUTION_BONUS
        for stat, amount in sorted(raw_boosts.items(), key=lambda x: x[1], reverse=True):
            if remaining <= 0:
                break
            add = min(amount, remaining)
            if add > 0:
                stat_boosts[stat] = add
            remaining -= add
    else:
        stat_boosts = raw_boosts

    # If no positive boosts emerged, fall back to boosting weakest stat by 1–2
    if not stat_boosts:
        weakest = min(_STAT_NAMES, key=lambda s: parent_stats[s])
        headroom = max_single - parent_stats[weakest]
        if headroom > 0:
            stat_boosts = {weakest: min(rng.randint(1, 3), headroom)}

    # --- Save updated pool (skip in test mode for determinism) ---
    if not _test_mode:
        save_gene_pool(gene_pool_path, tier, pool)

    win_rate  = float(analysis.get("win_rate", 0.5))
    new_ability_slot = win_rate < 0.40

    logger.bind(
        stage="genetic_evolution",
        tier=tier,
        stat_boosts=stat_boosts,
        fitness=round(parent_gene.fitness, 3),
        pool_size=len(pool),
    ).info("genetic | evolution decision")

    return {
        "stat_boosts":       stat_boosts,
        "new_ability_slot":  new_ability_slot,
        "reasoning": (
            f"GA evolution gen {parent_creature.get('generation', 0)}: "
            f"fitness={parent_gene.fitness:.2f}, "
            f"boosted={sorted(stat_boosts.keys())}"
        ),
    }

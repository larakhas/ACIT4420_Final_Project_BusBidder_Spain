# Architecture

## Components and flow of information

```mermaid
flowchart LR
    subgraph IN["Input files"]
        CSV["companies.csv<br/>destinations.csv<br/>offers.csv"]
        SET["settings.json"]
        PRO["profiles.json"]
    end
    subgraph LOAD["Loading"]
        LD["loader.py<br/>parse, validate,<br/>correct, quarantine"]
        CFG["config.py<br/>profiles.py"]
    end
    subgraph CORE["Core"]
        MK["marketplace.py<br/>facade"]
        REQ["request.py<br/>TravelRequest<br/>(Limit descriptor)"]
        RK["scoring.py<br/>Ranker, Weights<br/>@criterion @normaliser"]
        HC["constraints.py<br/>@hard_constraint"]
        BK["booking.py<br/>BookingStore"]
    end
    subgraph RES["Results"]
        EX["explain.py"]
        SE["sensitivity.py"]
        DI["display.py"]
    end
    CLI["cli.py<br/>subcommands +<br/>interactive mode"]
    REJ[("rejected_offers.csv")]
    BJS[("bookings.json")]
    LOG[("busbidder.log")]

    CSV --> LD
    SET --> CFG
    PRO --> CFG
    LD -->|valid offers| MK
    CFG --> MK
    CLI --> MK
    MK --> REQ --> RK
    RK --> HC
    MK <-->|seats booked| BK
    RK --> EX
    RK --> SE
    RK --> DI
    EX --> DI
    SE --> DI
    DI --> CLI
    LD --> REJ
    BK <--> BJS
    LD -.-> LOG
    RK -.-> LOG
    BK -.-> LOG
```

## Ranking pipeline

```mermaid
flowchart TD
    A["Traveller request<br/>profile + overrides"] --> B{"Scope:<br/>route and dates"}
    B -->|outside| X1["not part of<br/>this search"]
    B --> C{"Hard constraints:<br/>seats, budget, transfers,<br/>duration, luggage,<br/>changeable, refundable"}
    C -->|any broken| X2["excluded, every<br/>reason recorded"]
    C -->|all met| D["Score each used criterion 0-100<br/>relative: normaliser<br/>absolute: fixed rule"]
    D --> E{"Value<br/>missing?"}
    E -->|yes| F["neutral score 50,<br/>flagged with *"]
    E -->|no| G
    F --> G["Total = sum of<br/>weight x score"]
    G --> H["Sort: total, then price,<br/>departure, offer id"]
    H --> I["Explanation of #1,<br/>warnings"]
    I --> J["Optional booking:<br/>re-check seats and departure time, save"]
```

## Module responsibilities

| Module | Responsibility | Main names |
|---|---|---|
| `errors.py` | One exception hierarchy for every expected failure | `BusBidderError` and subclasses |
| `models.py` | Immutable domain objects | `Company`, `Destination`, `FareConditions`, `Offer`, `Booking` |
| `loader.py` | Read CSV files, validate, correct, quarantine | `load_catalogue`, `validate_offer`, `Catalogue` |
| `request.py` | What the traveller asked for | `TravelRequest`, `Limit` (descriptor), `DepartureWindow` |
| `constraints.py` | Hard constraints, registered by decorator | `@hard_constraint`, `apply_hard_constraints` |
| `scoring.py` | Normalisers, criteria, weights, ranker | `@normaliser`, `@criterion`, `Weights`, `Ranker` |
| `profiles.py` | Named traveller profiles read from JSON | `TravellerProfile`, `load_profiles` |
| `explain.py` | Explanation generated from the scores | `explain` |
| `sensitivity.py` | Does the winner survive weight changes? | `weight_sensitivity`, `normaliser_comparison` |
| `booking.py` | Simulated bookings, references, capacity | `BookingStore`, `parse_reference` |
| `marketplace.py` | Facade connecting the parts | `Marketplace` |
| `display.py` | Text formatting only | `render_*`, `table` |
| `cli.py` | Commands and interactive mode | `main`, `cmd_interactive` |
| `config.py`, `logging_setup.py` | Settings and log file | `Settings`, `configure_logging` |

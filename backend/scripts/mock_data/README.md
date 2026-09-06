# Mock data for RAG evaluation

Fabricated facts the base model can't already know, so a correct answer
proves retrieval worked (a wrong/generic answer means it's hallucinating).

## company.json (use `--loader json --chunker json`)

| Query | Expected answer |
|---|---|
| Who is the CEO of Zylotech Dynamics? | Amara Osei |
| Where is Zylotech Dynamics headquartered? | Nairobi, Kenya |
| How many employees does Zylotech Dynamics have? | 342 |
| What is Zylotech Dynamics' flagship product? | the Quantum Loom fabric printer |

## inventory.csv (use `--loader csv --chunker csv`)

| Query | Expected answer |
|---|---|
| What is the SKU for the Quantum Loom Filament? | ZD-2002 |
| How many units of the Nairobi Node Router are in stock? | 34 |
| What is the price of the Glimmer Wrench? | 49.99 |

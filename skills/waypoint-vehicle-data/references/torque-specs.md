# Torque Spec Lookup

The tech is standing under the car with a torque wrench. He needs a number that
matches THIS engine, not the model year, and he needs it fast.

## Rule: torque is engine-code specific, not model-year specific

A single model year is built with two or more engines that share almost no
fastener values. "2013 Sonata water pump" is not one answer — the 2.0L turbo and
the 2.4L use different pump designs with different bolt specs, and one of them
reuses the other's numbers in every generic table on the internet.

1. Get the engine from the vehicle record first — `decode-vin` returns
   `engine_size` / `engine_cylinders`, and `vehicle_specs` carries `engine_code`,
   `engine_vin_digit`, `engine_identity`. If those are empty, decode the VIN again;
   do not read the engine off the model name.
2. Pull the procedure for that exact engine variant (page titles carry it, e.g.
   `Sonata L4-2.0L Turbo` vs `Sonata L4-2.4L`).
3. Quote N·m and lb-ft together, name the fastener and what it fastens to, and
   flag the sibling-engine number when the two differ — that is the value he is
   most likely to have been handed by someone else.

## Method: Operation CHARM (charm.li) hosts real OEM manual text

It renders the Hyundai/Kia factory service manual nearly verbatim, including the
removal/installation procedures with each `Tightening torque :` line. Free, no
login.

**The index pages are JS-rendered.** `web_extract` on a `Repair and Diagnosis`
index returns a wall of `![](/icons/...)` lines and no links — that is the tree
failing to render, not a missing page. Enumerate the anchors in a browser instead:

```python
new_tab("https://charm.li/Hyundai/2013/Sonata%20L4-2.0L%20Turbo/Repair%20and%20Diagnosis/")
wait_for_load(); time.sleep(3)
paths = js("""(() => Array.from(document.querySelectorAll('a[name]'))
     .map(a=>a.getAttribute('name')))()""")
print([p for p in paths if re.search(r'belt|water', p, re.I)])
```

Enumerate `a[name]`, not `a[href]` and not link text. Folder nodes are
`href="javascript:void(0)"` until expanded, so an href/text filter on the collapsed
tree misses every leaf; each node's `name` attribute already carries its full path
string, expanded or not. One call lists the whole manual — filter it in Python
instead of spending a browser round-trip per guess.

Leaf pages (`.../Service and Repair/Repair Procedures/`, `.../Specifications/...`)
DO render through `web_extract` — read them there, not in the browser. Keep the
path segments exactly as the href gives them: spaces stay `%20`, commas stay
`%2C`, and `2.0L%20Turbo` / `2.4L` are separate manuals.

Useful URL shapes under `<Model L4-x.xL [Turbo]>/Repair and Diagnosis/`:

```
Engine, Cooling and Exhaust/Engine/<Component>/Service and Repair/Repair Procedures/
Engine, Cooling and Exhaust/Cooling System/<Component>/Service and Repair/Repair Procedures/
Specifications/Mechanical Specifications/<Component>/
Specifications/Mechanical Specifications/Engine/<Component>/
```

If both `Engine/<Component>/` and `Cooling System/<Component>/` exist they are the
same procedure under two trees — read one. A `404 page not found` means the
component is filed under the other tree, or the fastening point is described in a
neighbouring page (a pump bolted to the timing cover often appears in the Timing
Cover spec).

## Sources that waste time on specs

- **Templated spec sites** (hyundai-specs.com and clones). The pages return every
  heading with an empty value — `##### Torque Value` and nothing under it — and
  the search snippet supplies a number the page body does not contain. If the
  extracted body has headings with no values, discard the whole site, snippet
  included.
- **Generic "<model> torque specs" PDFs and Scribd uploads.** They merge engines
  under one model-year heading and label a sub-component as the main component.
- Parts listings, eBay fitment tables and dealer catalogs: they confirm which
  part fits, never what it torques to.

## Cross-check: pull the sibling engine's page

When a generic table and the OEM page disagree, load the *other* engine's page for
the same component. If the generic value matches the sibling engine exactly, you
have identified a transplanted spec — report it as such ("that 18.6–23.5 figure is
the 2.4L / the pump cover, not this pump body") instead of just giving the OEM
number. The tech needs to know which number he may already have been told.

## Domain note: Theta II (2011–2014 Sonata) water pump

| Fastener | 2.0L Turbo (G4KH) | 2.4L (G4KE) |
|---|---|---|
| Water pump sub-assembly to timing cover | 9.8–11.8 N·m (7.2–8.7 lb-ft) | 18.6–23.5 N·m (13.7–17.4 lb-ft) |
| Water pump cover (2.0T) / housing (2.4L) | 18.6–23.5 N·m (13.7–17.4 lb-ft) | 9.8–11.8 N·m bolt C, 18.6–23.5 N·m bolts D/E |
| Water pump pulley | 7.8–9.8 N·m (5.8–7.2 lb-ft) | 7.8–9.8 N·m (5.8–7.2 lb-ft) |
| Water inlet pipe | 9.8–11.8 N·m | 9.8–11.8 N·m |
| Exhaust manifold heat protector | 7.8–11.8 N·m | 7.8–11.8 N·m |

Both engines: small weeping from the pump bleed hole is normal per the manual;
steady coolant from it means the seal is gone and the pump is replaced.

## Persist what you looked up

The next service on the same VIN should not need the lookup repeated. Append the
fastener list to `vehicles.notes` under a `WATER PUMP TORQUE (...)` style heading
naming the engine, and note which sibling-engine figure NOT to use:

```bash
sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE vehicles SET notes = notes || char(10) || char(10) || '<COMPONENT> TORQUE (OEM service data, <engine>): <fastener> <N.m> (<lb-ft>); ...' WHERE id=<vehicle_id>;"
```

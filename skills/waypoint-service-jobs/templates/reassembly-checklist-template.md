# Major Reassembly Checklist Template

Use when a vehicle has undergone significant disassembly (body-off, engine pull, subframe drop, transmission R&R) and Mason is reassembling. He calls off completed items verbally; you track them.

## Workflow

1. Generate the checklist organized by vehicle system (see structure below).
2. Save to `~/.hermes/data/<vehicle>_reassembly_checklist.md` for persistence.
3. As Mason calls off completed items, patch the file — move items from REMAINING to COMPLETED.
4. Report a running tally count after each update.
5. Suggest likely next items based on physical proximity (e.g., "while you're in the left front wheel well — brake line, wheel speed sensor, ground straps").

## Checklist Structure (body-off / full separation)

Organize by system, roughly in reassembly order:

### Body & Structural
- Body mount bolts installed and torqued to spec
- Body mount isolators seated properly (no pinched/binding)

### Electrical
- Main chassis-to-body wiring harness connectors (count them — "4 rear plugs")
- Ground straps (engine-to-body, chassis-to-body)
- Wheel speed sensors (per wheel, if disconnected)
- Dangling connector sweep

### Steering
- Intermediate shaft bolt secured (splines aligned)
- Steering wheel straight / clockspring in range

### Fuel System
- Fuel line quick-connects at frame (per side)
- Fuel filler neck to tank (hose + clamp)
- Evap lines

### Cooling & HVAC
- Front and rear A/C lines
- Front and rear coolant lines
- Heater core hoses
- Coolant topped off and bled
- A/C system evacuated and recharged

### Brake System
- Brake lines per wheel (tighten)
- Brake system bled (if lines opened)
- Brake pedal firm (no air)

### Drivetrain
- Driveshaft bolts torqued (if disconnected)
- Transmission shift cable
- Transmission cooler lines
- Exhaust hangers (if separated)

### Fluids
- Power steering lines (low + high pressure)
- Engine oil
- Coolant
- Transmission fluid
- Power steering fluid
- Brake fluid

### Final Checks
- No tools left on chassis/frame
- No lines/harnesses pinched between body and frame
- Start engine — check for leaks
- A/C blows cold
- Shift through all gears
- Parking brake engages/releases
- Test drive — listen for noises, check temps

## Adaptation Rules

- **Not every job needs every section.** If Mason says "engine pull only," drop body mount, steering column, and fuel filler neck sections. Keep electrical, cooling, fluids, final.
- **Add items Mason mentions that aren't on the template.** If he says "got the parking brake cable attached" and there's no line item for it, add one. The template is a starting point, not exhaustive.
- **Group by physical location when Mason is working a specific area.** If he says "heading to left front wheel well," surface all items likely in that area — brake line, wheel speed sensor, ground strap, harness connector.
- **Mason works fast and calls off items in bulk.** Accept multiple items per message, mark them all, give a concise tally. Don't over-explain.

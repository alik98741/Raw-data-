import json
import smoke_aquacrop as ac

summary = []
for year in (2012, 2013):
    for trt in range(1, 13):
        print(f'Running AquaCrop: {year} treatment {trt}')
        summary.append(ac.run(year, trt))

with open(ac.OUT / 'all_24_summary.json', 'w') as f:
    json.dump(summary, f, indent=2, default=str)
print(json.dumps(summary, indent=2, default=str))

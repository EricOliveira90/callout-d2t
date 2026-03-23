## GMS

#### Scripts

**Callout**: `d2t run --recipe wbr_gms_callout --input main=wk10-full.tsv --input lookup=csv-static/PF-to-GL.csv --param period_label="WK10" -o wk10-gms-callout.md

**Detailed**: `d2t run --recipe wbr_gms_detailed --input main=wk10-full.tsv --input lookup=csv-static/PF-to-GL.csv -o wbr_gms_detailed_output.md`

#### Input format

year
merchant_customer_id
seller_name
product_group
channel
net_ordered_gms_usd

#### Output

Callout: [[wk10-gms-callout]]
**Detailed**: [[wk10-gms-detailed]]

## Selection

#### Scripts

**Callout**: `d2t run --recipe product_selection_callout --input main=wk-10-selection.tsv --input lookup=csv-static/PF-to-GL.csv`

**Detailed**: `d2t run --recipe product_selection_detailed --input main=wk-10-selection.tsv --input lookup=csv-static/PF-to-GL.csv -o wk10-selection-detailed.md`

#### Input format

period
product_group
is_fba
is_fbaos
is_es
is_ss
is_narf
mfn_ooc
is_ooc
mfn_dom
is_dom
is_ef_dom
ba
awagv
awas
ftac

#### Output

**Callout**: [[wk10-selection-callout]]
**Detailed**: [[wk10-selection-detailed]]
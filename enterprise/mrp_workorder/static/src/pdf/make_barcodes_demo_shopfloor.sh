#!/bin/sh

# Generated PDFs are written next to this script, regardless of the caller's cwd.
script_dir=$(cd "$(dirname "$0")" && pwd)

# make_sheet <sheet title> <output.pdf> <cells>
#
# <cells> is a sequence of 3-line groups, one per barcode, in the order they
# should appear on the page (first_row/col1, first_row/col2, row2/col1, ...; always 2
# columns):
#   <label shown above the barcode>
#   <value actually encoded in the barcode>
#   <text shown below the barcode>
#
# Known limitations:
# We can't skip a cell, so if you want to have a single barcode on a row, you need to put a dummy barcode in the other column.
# Over 7 rows, barcodes will print out of the page. If you want to have more than 7 rows, you need to create multiple sheets.
# If you don't exactly set 3 values per cell, values will be misaligned. The script does not check for this.
make_sheet () {
    sheet_title=$1
    out=$2
    cells=$3
    center_vertically=${4:-false}

    printf '%s\n' "$cells" | grep . > cells_TMP_FILE

    n_cells=$(wc -l < cells_TMP_FILE)
    n_cells=$(( n_cells / 3 ))
    rows=$(( (n_cells + 1) / 2 ))
    if ! $center_vertically; then
        rows=$(( rows < 7 ? 7 : rows )) # We could set 7 as a constant but we allow the user to mess up...
    fi

    # marginV keeps the row spacing identical.
    marginV=$(( (842 - 108 * rows) / 2 ))

    x_left=79
    x_right=336
    # y of 1st row title; each next row is 108pt lower.
    y_first_row=$(( 406 + 54 * rows ))

    barcodes=""
    headers=""
    idx=0
    while IFS= read -r cell_label && IFS= read -r cell_barcode && IFS= read -r cell_value; do
        row=$(( idx / 2 )) # 0 based
        if [ $(( idx % 2 )) -eq 0 ]; then x=$x_left; else x=$x_right; fi
        title_y=$(( y_first_row - 108 * row ))
        value_y=$(( title_y - 84 ))

        if [ -z "$barcodes" ]; then
            barcodes="$cell_barcode"
        else
            barcodes="$barcodes
$cell_barcode"
        fi
        headers="$headers
($cell_label) $x $title_y showTitle
($cell_value) $x $value_y showValue"

        idx=$(( idx + 1 ))
    done < cells_TMP_FILE
    rm cells_TMP_FILE

    barcode -t 2x${rows}+40+${marginV} -m 40x20 -p "210x297mm" -e code128b -n -o barcodes_TMP_FILE.ps << BARCODES
$barcodes
BARCODES

    cat > barcodesHeaders_TMP_FILE.ps << HEADER
/showTitle { /Helvetica-Bold findfont 12 scalefont setfont moveto show } def
/showValue { /Helvetica findfont 10 scalefont setfont moveto show } def
/showSheetTitle { /Helvetica-Bold findfont 16 scalefont setfont moveto show } def
($sheet_title) $x_left 810 showSheetTitle
$headers
HEADER

    cat barcodesHeaders_TMP_FILE.ps barcodes_TMP_FILE.ps | ps2pdf -sPAPERSIZE=a4 - "$out"
    rm barcodesHeaders_TMP_FILE.ps barcodes_TMP_FILE.ps
}

# Shop Floor Demo Sheet 1
make_sheet "Login and validate work orders" "$script_dir/barcodes_demo_shopfloor_sheet1.pdf" \
"Scan Employee Badge
041517863199
041517863199 - Ernest Reed

Scan Manufacturing Order
WH/MO/DEMO1
WH/MO/DEMO1

Select Work Center
drill1
drill1 - Drill 1

Start Work Order
OBTPAUS
OBTPAUS

Pause Work Order
OBTPAUS
OBTPAUS

Mark As Done
OBTCLWO
OBTCLWO

Select Work Center
assembly1
assembly1 - Assembly 1

Scan Manufacturing Order
WH/MO/DEMO1
WH/MO/DEMO1

Mark As Done
OBTCLWO
OBTCLWO

Scan Manufacturing Order
WH/MO/DEMO1
WH/MO/DEMO1

Close Production
OBTCLMO
OBTCLMO
"

# Shop Floor Demo Sheet 2
make_sheet "Consume components and validate production" "$script_dir/barcodes_demo_shopfloor_sheet2.pdf" \
"Scan Work Center
drill1
drill1 - Drill 1

Scan Manufacturing Order
WH/MO/DEMO2
WH/MO/DEMO2

Scan Product
601647855646
601647855646 - Drawer Black - FURN_2100

Scan Lot Number
0000000010001
0000000010001

Scan Product
601647855647
601647855647 - Drawer Case Black - FURN_5623

Scan Lot Number
0000000020045
0000000020045

Mark As Done
OBTCLWO
OBTCLWO

Select Work Center
assembly1
assembly1 - Assembly 1

Scan Manufacturing Order
WH/MO/DEMO2
WH/MO/DEMO2

Mark As Done
OBTCLWO
OBTCLWO

Scan Manufacturing Order
WH/MO/DEMO2
WH/MO/DEMO2

Close Production
OBTCLMO
OBTCLMO
"

# Merge the two sheets into a single PDF
gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -sOutputFile="$script_dir/barcodes_demo_shopfloor.pdf" \
    "$script_dir/barcodes_demo_shopfloor_sheet1.pdf" "$script_dir/barcodes_demo_shopfloor_sheet2.pdf"
rm "$script_dir/barcodes_demo_shopfloor_sheet1.pdf" "$script_dir/barcodes_demo_shopfloor_sheet2.pdf"

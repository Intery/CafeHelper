
_history_pattern = """\
{tip}```md
{day} ({tz}) (Page {page}/{page_count})

Period        | Duration | Focused  | Pattern
---------------------------------------------
{sessions}
+-----------------------------------+
{total}
```
"""
_history_session_pattern = (
    "{start} - {end} | {duration} | {focused} | {pattern}"
)
_history_total_pattern = (
    "{start} - {end} | {duration} | {focused}"
)



def codetable(
    headers: tuple[str, ...],
    data: tuple[tuple[str, ...], ...],
    title: str = '',
    synt: str = 'md',
    footer: str = '',
    justify: tuple[str, ...] | None = None,
    justify_head: tuple[str, ...] | None = None
) -> str:
    """
    ```{synt}
    {title}

    {headers[0]} | {headers[1]} | ...
    --------
    {data[0][0]} | {data[0][1]} | ...
    +----+
    {footer}
    ```
    """
    if not all(len(datum) == len(headers) for datum in data):
        raise ValueError("Table rows must be the same length as the headers.")
    if justify:
        if len(justify) != len(headers):
            raise ValueError("'justify' must be the same length as the table headers.")
    else:
        # Default to centre justify
        justify = ('^',) * len(headers)

    if justify_head:
        if len(justify_head) != len(headers):
            raise ValueError("'justify_head' must be the same length as the table headers.")
    else:
        justify_head = justify

    # Calculate column widths
    dataT = zip(headers, *data)  # Transposed
    widths = map(max, (map(len, col) for col in dataT))
    widths = [w for w in widths]

    # Format the headers and the data rows
    format_head = [f"{{col:{j}{w}}}" for j, w in zip(justify_head, widths)]
    format_parts = [f"{{col:{j}{w}}}" for j, w in zip(justify, widths)]
    formatted = []
    formatted.append(' | '.join(fstr.format(col=col) for fstr, col in zip(format_head, headers)))

    for row in data:
        middle = ' | '.join(fstr.format(col=col) for fstr, col in zip(format_parts, row)).rstrip()
        formatted.append(middle)
    rowlen = len(formatted[0])

    # Build the actual table
    rows = []
    rows.append(f"```{synt}")

    # Title, with extra space underneath
    if title:
        rows.append(title)
        rows.append('\n')

    rows.append(formatted[0])
    rows.append('-' * rowlen)
    rows.extend(formatted[1:])
    rows.append('+' + '-' * (rowlen - 2) + '+')
    if footer:
        rows.append(footer)
    rows.append('```')
    return '\n'.join(rows)

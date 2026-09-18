"""Transit ("в пути") warehouses — supplier goods on the way to a main
warehouse. They are kept ``is_active=False`` so they never surface on the site
or in any chart; their stock is shown only in the sales-stats «Текущий остаток»
block, grouped under the main warehouse they feed.
"""

# Transit warehouse name (as it comes from 1C) -> the main warehouse it feeds.
TRANSIT_PARENTS = {
    "Оптовый КемеровоТранзит (товар поставщиков в пути)(АМС)": "Кемерово",
    "Новокузнецк Транзит (АМС)": "Новокузнецк",
    "Склад Новосибирск Транзит (АМС)": "Новосибирск",
}

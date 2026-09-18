"""Transit ("в пути") warehouses — stock on the way to, or moving between, the
main warehouses. They are kept ``is_active=False`` so they never surface on the
site or in any chart; their stock is shown only in the sales-stats «Текущий
остаток» block, each under a short label.
"""

# Transit warehouse name (as it comes from 1C) -> label shown in the block.
# Supplier goods in transit are labelled by their destination warehouse;
# inter-warehouse transfers by the pair they move between (either direction).
TRANSIT_LABELS = {
    "Оптовый КемеровоТранзит (товар поставщиков в пути)(АМС)": "Кемерово",
    "Новокузнецк Транзит (АМС)": "Новокузнецк",
    "Склад Новосибирск Транзит (АМС)": "Новосибирск",
    "Склад транзит Кемерово-Нкз (АМС)": "Кемерово ↔ Новокузнецк",
    "Склад транзит Новосибирск-Нкз (АМС)": "Новосибирск ↔ Новокузнецк",
    "Склад транзит Кемерово-Новосибирск (АМС)": "Кемерово ↔ Новосибирск",
}

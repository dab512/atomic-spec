package fare

// atomic-spec://DEMO-FARE/DR-1
// Адаптер Go сохраняет согласованную нижнюю границу стоимости.
func MinimumFare() int { return 100 }

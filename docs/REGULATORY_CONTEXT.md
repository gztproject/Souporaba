# Regulatory context / Regulativni kontekst

This document maps Slovenian energy-sharing rules ([SODO — O souporabi](https://sodo.si/sl/souporaba-energije/souporaba)) to what the **Energy Sharing** Home Assistant integration does, what it does not do, and known gaps.

Ta dokument preslika pravila slovenske souporabe energije ([SODO — O souporabi](https://sodo.si/sl/souporaba-energije/souporaba)) na to, kaj integracija **Energy Sharing** v Home Assistant počne, česa ne počne in kje so znane vrzeli.

---

## Intended use / Predviden način uporabe

### English

The primary purpose of this integration is **not** to replace official billing from your electricity supplier or data from SODO / Moj Elektro.

It is designed for a **two-phase workflow** on the **Prejemnik (Receiver)** Home Assistant instance:

**Phase 1 — Calibration (before official sharing starts)**  
Run the integration with measured Oddajnik (Provider) grid export and Prejemnik grid import. Use export + percentage mode (or export-only) to observe real 15-minute behaviour **without relying on a guessed allocation percentage**. Review sensors such as `ideal_share_last_interval`, `required_share_last_interval`, `effective_allocation_percentage_last_interval`, and cumulative totals to derive an **evidence-based percentage** for your Moj Elektro registration.

**Phase 2 — Ongoing operation (after registration)**  
Keep the integration running through each month. Compare actual shared energy, consumption coverage, and unused shared energy against your registered percentage. Use the results to **adjust the share for the next month** in Moj Elektro (submit by the **10th** of the month for effect on the **1st** of the following month). Update `fixed_allocation_percentage` in integration options when the registered share changes.

The integration **recommends and monitors**; you **register and confirm** sharing in Moj Elektro.

### Slovenščina

Glavni namen integracije **ni** nadomestiti uradnega obračuna dobavitelja ali podatkov SODO / Moj Elektro.

Zasnovana je za **dvofazni potek** na instanci Home Assistant **prejemnika (Prejemnik)**:

**Faza 1 — Kalibracija (pred uradno souporabo)**  
Zaženite integracijo z izmerjenim omrežnim izvozom oddajnika in omrežnim prevzemom prejemnika. Uporabite način izvoz + odstotek (ali samo izvoz), da opazujete dejansko 15-minutno obnašanje **brez ugibanja odstotka dodelitve**. Preglejte senzorje, kot so `ideal_share_last_interval`, `required_share_last_interval`, `effective_allocation_percentage_last_interval`, in kumulativne vrednosti, da izpeljete **odstotek na podlagi meritev** za registracijo v Moj Elektro.

**Faza 2 — Tekoče delovanje (po registraciji)**  
Integracijo pustite v teku skozi mesec. Primerjajte dejansko souporabo, pokritost porabe in neuporabljeno souporabo z registriranim odstotkom. Rezultate uporabite za **prilagoditev deleža za naslednji mesec** v Moj Elektro (vlogo oddajte do **10.** v mesecu za začetek **1.** v naslednjem mesecu). Ko se registrirani delež spremeni, posodobite `fixed_allocation_percentage` v možnostih integracije.

Integracija **priporoča in spremlja**; vi **registrirate in potrjujete** souporabo v Moj Elektro.

---

## Rule mapping / Preslikava pravil

| # | SODO / regulatory rule | Integration behaviour | Gap / disclaimer |
|---|------------------------|----------------------|------------------|
| 1 | **15-minute settlement intervals** | Internal engine aligns to wall-clock `:00`, `:15`, `:30`, `:45`. | Intervals are derived from HA cumulative counters and processing delay, not from DSO interval stamps. May differ slightly from official data. |
| 1 | **15-minutni obračunski intervali** | Notranji mehanizem poravna na `:00`, `:15`, `:30`, `:45`. | Intervali izhajajo iz kumulativnih števcev HA in zakasnitve obdelave, ne iz časovnih žigov DSO. Lahko se nekoliko razlikujejo od uradnih podatkov. |
| 2 | **Oddajnik exports surplus; Prejemnik receives allocated share** | Runs on Prejemnik HA; reads receiver import, shared energy, optional provider export. | One Oddajnik ↔ one Prejemnik pair only. No multi-receiver split. |
| 2 | **Oddajnik oddaja presežek; prejemnik prejme dodeljen delež** | Teče na HA prejemnika; bere prevzem, souporabo, neobvezno izvoz oddajnika. | Samo en par oddajnik ↔ prejemnik. Brez razdelitve na več prejemnikov. |
| 3 | **Share = % of grid-exported energy per interval** | Export + percentage: `expected_shared = export × % / 100`. | Percentage-only mode infers export from shared energy — use for calibration only, not as regulatory truth. |
| 3 | **Delež = % od v omrežje oddane energije na interval** | Izvoz + odstotek: `pričakovana_souporaba = izvoz × % / 100`. | Način samo z odstotkom sklepa izvoz iz souporabe — za kalibracijo, ne kot regulativna resnica. |
| 4 | **Same % for all intervals in a month; change monthly in Moj Elektro** | Single `fixed_allocation_percentage` in options until you change it. | No Moj Elektro sync. You must update HA options when the registered % changes. |
| 4 | **Enak % za vse intervale v mesecu; mesečna sprememba v Moj Elektro** | En `fixed_allocation_percentage` v možnostih, dokler ga ne spremenite. | Brez sinhronizacije z Moj Elektro. Ob spremembi registriranega % posodobite možnosti v HA. |
| 5 | **Administrative transfer, not physical grid flow** | Treats shared energy as accounting allocation from cumulative counters. | Correct model; document that MQTT-mirrored counters are your responsibility. |
| 5 | **Administrativni prenos, ne fizični pretok** | Souporabo obravnava kot računovodsko dodelitev iz kumulativnih števcev. | Pravilen model; zanesljivost MQTT zrcaljenih števcev je vaša odgovornost. |
| 6 | **Energy credit only up to actual consumption** | `used_shared = min(shared, import)`. | Matches supplier billing rule for Prejemnik. |
| 6 | **Znižanje samo do višine dejanske porabe** | `uporabljena_souporaba = min(souporaba, prevzem)`. | Skladno s pravilom obračuna dobavitelja za prejemnika. |
| 7 | **Unused shared energy goes to supplier** | `unused_shared = max(shared - import, 0)`. | Correct for standard Prejemnik-only-import case. |
| 7 | **Neuporabljena souporaba pripada dobavitelju** | `neuporabljena = max(souporaba - prevzem, 0)`. | Velja za standardni primer prejemnika brez izvoza. |
| 8 | **Sharing affects energy commodity only, not omrežnina** | `billable_energy = max(import - shared, 0)` is energy still owed on the **energy** line. Full `receiver_import` remains the basis for network charges. | Sensor name `billable_energy` means supplier energy charge, **not** omrežnina. Integration does not calculate omrežnina. |
| 8 | **Souporaba vpliva samo na energijo, ne na omrežnino** | `billable_energy` = energija, ki še ostane na postavki **energije**. Celoten `receiver_import` še vedno velja za omrežnino. | Senzor `billable_energy` pomeni energijo pri dobavitelju, **ne** omrežnino. Integracija ne izračunava omrežnine. |
| 9 | **Register in Moj Elektro; both parties confirm** | Out of scope. | User action in Moj Elektro portal. Integration does not register or confirm. |
| 9 | **Registracija v Moj Elektro; potrdita oba** | Izven obsega. | Uporabnik v portalu Moj Elektro. Integracija ne registrira in ne potrjuje. |
| 10 | **Submit by 10th for start on 1st next month** | Out of scope. | Use calendar reminders. Monthly sensors can inform your decision. |
| 10 | **Vloga do 10. za začetek 1. v naslednjem mesecu** | Izven obsega. | Uporabite koledarske opomnike. Mesečni senzorji podpirajo odločitev. |
| 11 | **Prejemnik cannot be on annual net metering (EZ-1)** | Not validated. | User must verify eligibility before registering. |
| 11 | **Prejemnik ne sme imeti letnega net meteringa (EZ-1)** | Ni preverjano. | Uporabnik mora preveriti upravičenost pred registracijo. |
| 12 | **EZ-1 Oddajnik: shared energy deducted from export each interval** | Not modeled on Oddajnik side. | Integration is Prejemnik-centric. Oddajnik annual netting is outside scope. |
| 12 | **EZ-1 oddajnik: souporaba se odšteje od izvoza na interval** | Na strani oddajnika ni modelirano. | Integracija je osredotočena na prejemnika. Letno netiranje oddajnika je izven obsega. |
| 13 | **One Oddajnik, multiple Prejemniki (shares ≤ 100%)** | Single pair only. | Cannot model remaining % allocated to other receivers. |
| 13 | **En oddajnik, več prejemnikov (vsota deležev ≤ 100 %)** | Samo en par. | Ni modeliranja preostalega deleža za druge prejemnike. |
| 14 | **Official data from DSO / Moj Elektro** | Uses user-configured HA cumulative sensors. | Not authoritative. For monitoring and calibration, not legal billing proof. |
| 14 | **Uradni podatki DSO / Moj Elektro** | Uporablja kumulativne senzorje HA. | Ni uradni vir. Za spremljanje in kalibracijo, ne za pravni dokaz obračuna. |
| 15 | **Contractual price between parties** | Out of scope. | Integration tracks kWh only, not EUR. |
| 15 | **Pogodbeni cenik med strankama** | Izven obsega. | Integracija spremlja kWh, ne EUR. |
| 16 | **Prejemnik exports in same interval** | Only receiver **import** is tracked, not export. | If Prejemnik also exports, official settlement may differ. |
| 16 | **Prejemnik izvaža v istem intervalu** | Spremlja se samo **prevzem**, ne izvoz. | Če prejemnik tudi izvaža, uradni obračun lahko odstopa. |
| 17 | **Energy from renewable sources** | Not validated. | User must ensure Oddajnik meets legal requirements. |
| 17 | **Energija iz obnovljivih virov** | Ni preverjano. | Uporabnik mora zagotoviti skladnost oddajnika. |

---

## Key sensors for your workflow / Ključni senzorji za vaš potek

| Sensor | Calibration (before go-live) | Ongoing (monthly tuning) |
|--------|-------------------------------|--------------------------|
| `ideal_share_last_interval` | Shows what % would have covered consumption each interval | Spot intervals where registered % is too low/high |
| `required_share_last_interval` | Raw required % before capping at 100% | Same |
| `effective_allocation_percentage_last_interval` | Actual % achieved (shared ÷ export) | Compare with registered % |
| `unused_shared_last_interval` | Predict energy lost to supplier if % is too high | Tune down % if consistently high |
| `billable_energy_last_interval` | Energy still on supplier energy bill after sharing | Cost-relevant kWh check |
| `allocation_utilization_last_interval` | How much of allocated share was consumed | Efficiency of chosen % |
| `total_*` cumulative sensors | Month-level evidence for Moj Elektro % choice | Month-over-month comparison |

| Senzor | Kalibracija (pred souporabo) | Tekoče (mesečna prilagoditev) |
|--------|-------------------------------|-------------------------------|
| `ideal_share_last_interval` | Kakšen % bi pokril porabo v intervalu | Intervali, kjer je registrirani % prenizek/visok |
| `required_share_last_interval` | Zahtevan % pred omejitvijo na 100 % | Enako |
| `effective_allocation_percentage_last_interval` | Dejanski % (souporaba ÷ izvoz) | Primerjava z registriranim % |
| `unused_shared_last_interval` | Napoved izgube energije dobavitelju | Znižajte %, če je stalno visoka |
| `billable_energy_last_interval` | Energija na računu dobavitelja po souporabi | Preverjanje kWh |
| `allocation_utilization_last_interval` | Koliko dodeljene souporabe je bilo porabljeno | Učinkovitost izbranega % |
| `total_*` kumulativni senzorji | Mesečni dokazi za izbiro % v Moj Elektro | Primerjava med meseci |

---

## Disclaimers / Izjave o omejitvi odgovornosti

### English

1. **Not official billing** — Supplier invoices and Moj Elektro data prevail over this integration.
2. **Not legal advice** — Eligibility, contracts, and registration are your responsibility.
3. **Pre-go-live data** — Before official sharing, `shared_energy_total_source` may be simulated or zero; export + percentage mode with measured Oddajnik export is the recommended calibration setup.
4. **Omrežnina** — Network charges and other levies use full meter import; only the energy commodity line is reduced by sharing.
5. **Manual Moj Elektro step** — Changing the registered percentage requires the Moj Elektro portal (by the 10th of the month). The integration does not submit registrations.
6. **Single pair** — Does not model multiple Prejemniki or Organizator souporabe workflows.

### Slovenščina

1. **Ni uradni obračun** — Za veljavnost veljata račun dobavitelja in podatki Moj Elektro.
2. **Ni pravni nasvet** — Upravičenost, pogodbe in registracija so vaša odgovornost.
3. **Podatki pred souporabo** — Pred uradno souporabo je `shared_energy_total_source` lahko simuliran ali nič; za kalibracijo priporočamo način izvoz + odstotek z izmerjenim izvozom oddajnika.
4. **Omrežnina** — Omrežnina in drugi prispevki temeljijo na celotnem števčnem prevzemu; souporaba zniža samo postavko energije.
5. **Ročni korak v Moj Elektro** — Sprememba registriranega odstotka poteka v portalu Moj Elektro (do 10. v mesecu). Integracija ne oddaja vlog.
6. **En par** — Ne modelira več prejemnikov ali vloge organizatorja souporabe.

---

## References / Viri

- [SODO — O souporabi](https://sodo.si/sl/souporaba-energije/souporaba)
- [Elektro Maribor — Vprašanja in odgovori (souporaba)](https://www.elektro-maribor.si/za-uporabnike/kontaktna-to%C4%8Dka-souporabe/vpra%C5%A1anja-in-odgovori/)
- [docs/INPUT_ENTITIES.md](INPUT_ENTITIES.md) — technical input model

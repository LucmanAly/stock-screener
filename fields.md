# Available fields

Rows: **503**  
Columns: **236**  
Generated: 2026-09-16T02:49:30.660989+00:00

Computed columns are grouped first; everything after `-- yfinance .info --`
is passed through untouched from the Yahoo snapshot.

## Classification

| column | non-null | coverage | dtype | example |
| --- | --: | --: | --- | --- |
| `symbol` | 503 | 100.0% | str | A |
| `gics_sector` | 503 | 100.0% | str | Health Care |
| `gics_sub_industry` | 503 | 100.0% | str | Life Sciences Tools & Services |
| `sector` | 503 | 100.0% | str | Healthcare |
| `industry` | 502 | 99.8% | str | Diagnostics & Research |
| `peer_group` | 503 | 100.0% | object | Diagnostics & Research |
| `peer_level` | 503 | 100.0% | object | yahoo_industry |

## Statement-derived

| column | non-null | coverage | dtype | example |
| --- | --: | --: | --- | --- |
| `roic` | 469 | 93.2% | float64 | 0.16911581988923668 |
| `revenue_cagr_3y` | 501 | 99.6% | float64 | 0.004844098070605929 |
| `eps_cagr_3y` | 426 | 84.7% | float64 | 0.030180455204013246 |
| `fcf_cagr_3y` | 415 | 82.5% | float64 | 0.04105956570895941 |
| `fcf_conversion` | 475 | 94.4% | float64 | 0.884113584036838 |
| `interest_coverage` | 433 | 86.1% | float64 | 13.8125 |
| `net_debt_to_ebitda` | 444 | 88.3% | float64 | 0.8528610354223434 |
| `gross_margin_stdev_5y` | 451 | 89.7% | float64 | 0.017393939765833748 |
| `equity_ratio` | 503 | 100.0% | float64 | 0.5296613498860689 |

## Estimates

| column | non-null | coverage | dtype | example |
| --- | --: | --: | --- | --- |
| `eps_fy1_current` | 500 | 99.4% | float64 | 6.20196 |
| `eps_fy1_7d` | 500 | 99.4% | float64 | 6.20221 |
| `eps_fy1_30d` | 500 | 99.4% | float64 | 6.06094 |
| `eps_fy1_60d` | 500 | 99.4% | float64 | 6.06194 |
| `eps_fy1_90d` | 500 | 99.4% | float64 | 6.06038 |
| `eps_fy2_current` | 500 | 99.4% | float64 | 6.75735 |
| `eps_fy2_7d` | 500 | 99.4% | float64 | 6.7636 |
| `eps_fy2_30d` | 500 | 99.4% | float64 | 6.6108 |
| `eps_fy2_60d` | 500 | 99.4% | float64 | 6.61223 |
| `eps_fy2_90d` | 500 | 99.4% | float64 | 6.60636 |
| `eps_fy1_avg` | 500 | 99.4% | float64 | 6.20196 |
| `eps_fy1_analysts` | 500 | 99.4% | float64 | 22.0 |
| `eps_fy1_growth` | 495 | 98.4% | float64 | 0.1095 |
| `eps_fy2_avg` | 500 | 99.4% | float64 | 6.75735 |
| `eps_fy2_analysts` | 500 | 99.4% | float64 | 23.0 |
| `eps_fy2_growth` | 498 | 99.0% | float64 | 0.0896 |
| `revenue_est_next_year` | 502 | 99.8% | float64 | 7985882610.0 |

## Earnings surprises

| column | non-null | coverage | dtype | example |
| --- | --: | --: | --- | --- |
| `surprise_pct_1` | 499 | 99.2% | float64 | 0.090100005 |
| `surprise_pct_2` | 498 | 99.0% | float64 | 0.058000002 |
| `surprise_pct_3` | 498 | 99.0% | float64 | -0.006 |
| `surprise_pct_4` | 495 | 98.4% | float64 | 0.0037 |

## Price factors

| column | non-null | coverage | dtype | example |
| --- | --: | --: | --- | --- |
| `momentum_12_1` | 500 | 99.4% | float64 | 0.19176859708524208 |
| `return_6m` | 501 | 99.6% | float64 | 0.3532649882476775 |
| `rs_6m_vs_spy` | 501 | 99.6% | float64 | 0.17708983889738983 |
| `rs_6m_vs_sector` | 501 | 99.6% | float64 | 0.1232818966005742 |
| `pct_below_52w_high` | 503 | 100.0% | float64 | 0.05490563350653498 |
| `price_vs_200dma` | 501 | 99.6% | float64 | 0.1456142592645011 |

## -- yfinance .info --

| column | non-null | coverage | dtype | example |
| --- | --: | --: | --- | --- |
| `marketCap` | 502 | 99.8% | float64 | 42371006464.0 |
| `trailingPE` | 477 | 94.8% | float64 | 29.009655 |
| `forwardPE` | 503 | 100.0% | float64 | 22.238008 |
| `priceToBook` | 498 | 99.0% | float64 | 5.754605 |
| `enterpriseToEbitda` | 471 | 93.6% | float64 | 21.517 |
| `freeCashflow` | 470 | 93.4% | float64 | 1060374976.0 |
| `operatingMargins` | 502 | 99.8% | float64 | 0.25559 |
| `profitMargins` | 502 | 99.8% | float64 | 0.19533001 |
| `returnOnEquity` | 469 | 93.2% | float64 | 0.20971 |
| `revenueGrowth` | 502 | 99.8% | float64 | 0.081 |
| `earningsGrowth` | 458 | 91.1% | float64 | 0.085 |
| `debtToEquity` | 450 | 89.5% | float64 | 56.336 |
| `beta` | 497 | 98.8% | float64 | 1.241 |
| `fiftyTwoWeekHigh` | 503 | 100.0% | float64 | 163.75 |
| `currentPrice` | 503 | 100.0% | float64 | 150.27 |
| `targetMeanPrice` | 499 | 99.2% | float64 | 174.95238 |
| `numberOfAnalystOpinions` | 499 | 99.2% | float64 | 21.0 |
| `52WeekChange` | 502 | 99.8% | float64 | 0.15845954 |
| `SandP52WeekChange` | 502 | 99.8% | float64 | 0.15448117 |
| `address1` | 502 | 99.8% | str | 5301 Stevens Creek Boulevard |
| `address2` | 126 | 25.0% | str | Ground Floor 100 Pitts Bay Road |
| `allTimeHigh` | 503 | 100.0% | float64 | 179.57 |
| `allTimeLow` | 503 | 100.0% | float64 | 7.51073 |
| `ask` | 503 | 100.0% | float64 | 151.39 |
| `askSize` | 503 | 100.0% | int64 | 400 |
| `auditRisk` | 495 | 98.4% | float64 | 8.0 |
| `averageAnalystRating` | 446 | 88.7% | str | 1.7 - Buy |
| `averageDailyVolume10Day` | 503 | 100.0% | int64 | 2109360 |
| `averageDailyVolume3Month` | 503 | 100.0% | int64 | 2190254 |
| `averageVolume` | 503 | 100.0% | int64 | 2190254 |
| `averageVolume10days` | 503 | 100.0% | int64 | 2109360 |
| `bid` | 503 | 100.0% | float64 | 150.2 |
| `bidSize` | 503 | 100.0% | int64 | 200 |
| `boardRisk` | 495 | 98.4% | float64 | 3.0 |
| `bookValue` | 498 | 99.0% | float64 | 26.113 |
| `city` | 502 | 99.8% | str | Santa Clara |
| `companyOfficers` | 502 | 99.8% | str | [{"maxAge": 1, "name": "Mr. Padra... |
| `compensationAsOfEpochDate` | 500 | 99.4% | float64 | 1767139200.0 |
| `compensationRisk` | 495 | 98.4% | float64 | 7.0 |
| `corporateActions` | 503 | 100.0% | str | [] |
| `country` | 502 | 99.8% | str | United States |
| `cryptoTradeable` | 503 | 100.0% | bool | False |
| `currency` | 503 | 100.0% | str | USD |
| `currentRatio` | 483 | 96.0% | float64 | 2.05 |
| `customPriceAlertConfidence` | 503 | 100.0% | str | HIGH |
| `dateShortInterest` | 502 | 99.8% | float64 | 1788134400.0 |
| `dayHigh` | 503 | 100.0% | float64 | 150.96 |
| `dayLow` | 503 | 100.0% | float64 | 147.55 |
| `displayName` | 418 | 83.1% | str | Agilent |
| `dividendDate` | 415 | 82.5% | float64 | 1784678400.0 |
| `dividendRate` | 404 | 80.3% | float64 | 1.02 |
| `dividendYield` | 404 | 80.3% | float64 | 0.69 |
| `earningsCallTimestampEnd` | 492 | 97.8% | float64 | 1787774400.0 |
| `earningsCallTimestampStart` | 492 | 97.8% | float64 | 1787774400.0 |
| `earningsQuarterlyGrowth` | 461 | 91.7% | float64 | 0.077 |
| `earningsTimestamp` | 487 | 96.8% | float64 | 1787774400.0 |
| `earningsTimestampEnd` | 503 | 100.0% | int64 | 1795636800 |
| `earningsTimestampStart` | 503 | 100.0% | int64 | 1795636800 |
| `ebitda` | 472 | 93.8% | float64 | 2080000000.0 |
| `ebitdaMargins` | 502 | 99.8% | float64 | 0.28215 |
| `enterpriseToRevenue` | 500 | 99.4% | float64 | 6.071 |
| `enterpriseValue` | 500 | 99.4% | float64 | 44755447808.0 |
| `epsCurrentYear` | 497 | 98.8% | float64 | 6.20196 |
| `epsForward` | 503 | 100.0% | float64 | 6.75735 |
| `epsTrailingTwelveMonths` | 503 | 100.0% | float64 | 5.18 |
| `esgPopulated` | 503 | 100.0% | bool | False |
| `exDividendDate` | 422 | 83.9% | float64 | 1782777600.0 |
| `exchange` | 503 | 100.0% | str | NYQ |
| `exchangeDataDelayedBy` | 503 | 100.0% | int64 | 0 |
| `exchangeTimezoneName` | 503 | 100.0% | str | America/New_York |
| `exchangeTimezoneShortName` | 503 | 100.0% | str | EDT |
| `exchangeTransferDate` | 1 | 0.2% | str | 2026-09-14 |
| `executiveTeam` | 502 | 99.8% | str | [] |
| `fax` | 77 | 15.3% | str | 441 278 9255 |
| `fiftyDayAverage` | 503 | 100.0% | float64 | 143.5834 |
| `fiftyDayAverageChange` | 503 | 100.0% | float64 | 6.6865997 |
| `fiftyDayAverageChangePercent` | 503 | 100.0% | float64 | 0.046569448 |
| `fiftyTwoWeekChangePercent` | 503 | 100.0% | float64 | 15.845955 |
| `fiftyTwoWeekHighChange` | 503 | 100.0% | float64 | -13.479996 |
| `fiftyTwoWeekHighChangePercent` | 503 | 100.0% | float64 | -0.082320586 |
| `fiftyTwoWeekLow` | 503 | 100.0% | float64 | 108.35 |
| `fiftyTwoWeekLowChange` | 503 | 100.0% | float64 | 41.920006 |
| `fiftyTwoWeekLowChangePercent` | 503 | 100.0% | float64 | 0.38689438 |
| `fiftyTwoWeekRange` | 503 | 100.0% | str | 108.35 - 163.75 |
| `financialCurrency` | 502 | 99.8% | str | USD |
| `firstTradeDateMilliseconds` | 503 | 100.0% | int64 | 942935400000 |
| `fiveYearAvgDividendYield` | 392 | 77.9% | float64 | 0.69 |
| `floatShares` | 500 | 99.4% | float64 | 280964657.0 |
| `forwardEps` | 502 | 99.8% | float64 | 6.75735 |
| `fullExchangeName` | 503 | 100.0% | str | NYSE |
| `fullTimeEmployees` | 499 | 99.2% | float64 | 18200.0 |
| `fulldayChange` | 503 | 100.0% | float64 | 2.9799957 |
| `fulldayChangePercent` | 503 | 100.0% | float64 | 2.0299697 |
| `fulldayPrice` | 503 | 100.0% | float64 | 150.27 |
| `gmtOffSetMilliseconds` | 503 | 100.0% | int64 | -14400000 |
| `governanceEpochDate` | 495 | 98.4% | float64 | 1788220800.0 |
| `grossMargins` | 502 | 99.8% | float64 | 0.53648996 |
| `grossProfits` | 502 | 99.8% | float64 | 3955000064.0 |
| `hasPrePostMarketData` | 503 | 100.0% | bool | True |
| `heldPercentInsiders` | 502 | 99.8% | float64 | 0.00195 |
| `heldPercentInstitutions` | 502 | 99.8% | float64 | 0.95468 |
| `impliedSharesOutstanding` | 502 | 99.8% | float64 | 281965813.0 |
| `industryDisp` | 502 | 99.8% | str | Diagnostics & Research |
| `industryKey` | 502 | 99.8% | str | diagnostics-research |
| `ipoExpectedDate` | 17 | 3.4% | str | 2020-12-10 |
| `irWebsite` | 326 | 64.8% | str | http://www.investor.agilent.com/p... |
| `isEarningsDateEstimate` | 503 | 100.0% | bool | True |
| `language` | 503 | 100.0% | str | en-US |
| `lastDividendDate` | 422 | 83.9% | float64 | 1782777600.0 |
| `lastDividendValue` | 422 | 83.9% | float64 | 0.255 |
| `lastFiscalYearEnd` | 502 | 99.8% | float64 | 1761868800.0 |
| `lastSplitDate` | 361 | 71.8% | float64 | 1414972800.0 |
| `lastSplitFactor` | 361 | 71.8% | str | 1398:1000 |
| `longBusinessSummary` | 502 | 99.8% | str | Agilent Technologies, Inc. provid... |
| `longName` | 503 | 100.0% | str | Agilent Technologies, Inc. |
| `market` | 503 | 100.0% | str | us_market |
| `marketState` | 503 | 100.0% | str | POSTPOST |
| `maxAge` | 503 | 100.0% | int64 | 86400 |
| `messageBoardId` | 503 | 100.0% | str | finmb_154924 |
| `mostRecentQuarter` | 502 | 99.8% | float64 | 1785456000.0 |
| `nameChangeDate` | 44 | 8.7% | str | 2026-09-15 |
| `netIncomeToCommon` | 501 | 99.6% | float64 | 1440000000.0 |
| `nextFiscalYearEnd` | 502 | 99.8% | float64 | 1793404800.0 |
| `nonDilutedMarketCap` | 503 | 100.0% | int64 | 41387155767 |
| `open` | 503 | 100.0% | float64 | 147.0 |
| `operatingCashflow` | 502 | 99.8% | float64 | 1608999936.0 |
| `overallRisk` | 495 | 98.4% | float64 | 5.0 |
| `payoutRatio` | 502 | 99.8% | float64 | 0.1998 |
| `pegRatio` | 496 | 98.6% | float64 | 1.21 |
| `phone` | 501 | 99.6% | str | 800 227 9770 |
| `postMarketChange` | 502 | 99.8% | float64 | 0.0 |
| `postMarketChangePercent` | 502 | 99.8% | float64 | 0.0 |
| `postMarketPrice` | 502 | 99.8% | float64 | 150.27 |
| `postMarketTime` | 502 | 99.8% | float64 | 1789510149.0 |
| `prevExchange` | 1 | 0.2% | str | NGM |
| `prevName` | 44 | 8.7% | str | American Tower Corporation (REIT) |
| `previousClose` | 503 | 100.0% | float64 | 146.8 |
| `priceEpsCurrentYear` | 497 | 98.8% | float64 | 24.229437 |
| `priceHint` | 503 | 100.0% | int64 | 2 |
| `priceToSalesTrailing12Months` | 501 | 99.6% | float64 | 5.747559 |
| `quickRatio` | 483 | 96.0% | float64 | 1.414 |
| `quoteSourceName` | 497 | 98.8% | str | Delayed Quote |
| `quoteType` | 503 | 100.0% | str | EQUITY |
| `recommendationKey` | 503 | 100.0% | str | buy |
| `recommendationMean` | 446 | 88.7% | float64 | 1.73913 |
| `region` | 503 | 100.0% | str | US |
| `regularMarketChange` | 503 | 100.0% | float64 | 3.47 |
| `regularMarketChangePercent` | 503 | 100.0% | float64 | 2.36376 |
| `regularMarketDayHigh` | 503 | 100.0% | float64 | 150.96 |
| `regularMarketDayLow` | 503 | 100.0% | float64 | 147.55 |
| `regularMarketDayRange` | 503 | 100.0% | str | 147.55 - 150.96 |
| `regularMarketOpen` | 503 | 100.0% | float64 | 147.0 |
| `regularMarketPreviousClose` | 503 | 100.0% | float64 | 146.8 |
| `regularMarketPrice` | 503 | 100.0% | float64 | 150.27 |
| `regularMarketTime` | 503 | 100.0% | int64 | 1789502644 |
| `regularMarketVolume` | 503 | 100.0% | int64 | 1585341 |
| `returnOnAssets` | 498 | 99.0% | float64 | 0.086330004 |
| `revenuePerShare` | 501 | 99.6% | float64 | 26.096 |
| `sectorDisp` | 502 | 99.8% | str | Healthcare |
| `sectorKey` | 502 | 99.8% | str | healthcare |
| `shareHolderRightsRisk` | 495 | 98.4% | float64 | 6.0 |
| `sharesOutstanding` | 502 | 99.8% | float64 | 281965813.0 |
| `sharesPercentSharesOut` | 502 | 99.8% | float64 | 0.0201 |
| `sharesShort` | 502 | 99.8% | float64 | 5677007.0 |
| `sharesShortPreviousMonthDate` | 502 | 99.8% | float64 | 1785456000.0 |
| `sharesShortPriorMonth` | 502 | 99.8% | float64 | 5749623.0 |
| `shortName` | 503 | 100.0% | str | Agilent Technologies, Inc. |
| `shortPercentOfFloat` | 498 | 99.0% | float64 | 0.0229 |
| `shortRatio` | 502 | 99.8% | float64 | 2.76 |
| `sourceInterval` | 503 | 100.0% | int64 | 15 |
| `state` | 479 | 95.2% | str | CA |
| `targetHighPrice` | 499 | 99.2% | float64 | 190.0 |
| `targetLowPrice` | 499 | 99.2% | float64 | 155.0 |
| `targetMedianPrice` | 499 | 99.2% | float64 | 175.0 |
| `totalCash` | 501 | 99.6% | float64 | 1758000000.0 |
| `totalCashPerShare` | 500 | 99.4% | float64 | 6.236 |
| `totalDebt` | 501 | 99.6% | float64 | 4148000000.0 |
| `totalRevenue` | 502 | 99.8% | float64 | 7372000256.0 |
| `tradeable` | 503 | 100.0% | bool | False |
| `trailingAnnualDividendRate` | 503 | 100.0% | float64 | 1.013 |
| `trailingAnnualDividendYield` | 503 | 100.0% | float64 | 0.0069005447 |
| `trailingEps` | 502 | 99.8% | float64 | 5.18 |
| `trailingPegRatio` | 431 | 85.7% | float64 | 1.2122 |
| `triggerable` | 503 | 100.0% | bool | True |
| `twoHundredDayAverage` | 503 | 100.0% | float64 | 131.541 |
| `twoHundredDayAverageChange` | 503 | 100.0% | float64 | 18.729004 |
| `twoHundredDayAverageChangePercent` | 503 | 100.0% | float64 | 0.14238149 |
| `typeDisp` | 503 | 100.0% | str | Equity |
| `volume` | 503 | 100.0% | int64 | 1585341 |
| `website` | 502 | 99.8% | str | https://www.agilent.com |
| `zip` | 501 | 99.6% | str | 95051 |
| `wiki_name` | 503 | 100.0% | str | Agilent Technologies |
| `fetched_at` | 503 | 100.0% | str | 2026-09-16T02:36:22.977419+00:00 |

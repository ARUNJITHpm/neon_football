"""Descriptive intervals; independence assumptions are reported by the evaluator."""
import math


def proportion(successes, total):
    if not total:
        return dict(value=None, numerator=successes, denominator=total, ci95=None)
    p, z = successes / total, 1.959963984540054
    divisor = 1 + z*z/total
    center = (p + z*z/(2*total)) / divisor
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / divisor
    return dict(value=p, numerator=successes, denominator=total,
                ci95=[max(0, center-radius), min(1, center+radius)], interval_method="wilson")


def poisson_rate(count, hours):
    if hours == 0:
        return dict(value=None, count=count, hours=hours, ci95=None)

    def cdf(k, mean):
        if mean == 0:
            return 1.0
        logs = [-mean + i*math.log(mean) - math.lgamma(i+1) for i in range(k+1)]
        maximum = max(logs)
        return min(1, math.exp(maximum) * math.fsum(math.exp(v-maximum) for v in logs))

    def invert(k, target):
        low, high = 0.0, max(10, k + 10*math.sqrt(k+1) + 20)
        while cdf(k, high) > target:
            high *= 2
        for _ in range(70):
            middle = (low+high)/2
            if cdf(k, middle) > target:
                low = middle
            else:
                high = middle
        return (low+high)/2

    lower = invert(count-1, 0.975) if count else 0
    upper = invert(count, 0.025)
    return dict(value=count/hours, count=count, hours=hours, ci95=[lower/hours, upper/hours], interval_method="exact-central-poisson")


def distribution(values):
    if not values:
        return dict(samples=0, p50=None, p95=None, p99=None, maximum=None)
    ordered = sorted(values)
    def q(probability):
        return ordered[max(0, math.ceil(probability*len(ordered))-1)]
    return dict(samples=len(values), p50=q(.5), p95=q(.95), p99=q(.99), maximum=max(values))

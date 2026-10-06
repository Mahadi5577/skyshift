"""Guided tour: hand-picked stops that each teach one idea. Precache them before a demo."""

STOPS = [
    {
        "id": "hygiea",
        "title": "Watch an asteroid crawl",
        "zoom": "hours",
        "ra": 95.60007, "dec": 25.04644, "wave": 1.31,
        "t_min": 60948.30, "t_max": 60948.45,
        "blurb": "On 30 September 2025, SPHEREx photographed the giant asteroid (10) Hygiea "
                 "several times in under two hours. The stars stay put; Hygiea, about 2.8 times "
                 "farther from the Sun than Earth, slides 32 arcseconds across the frame. "
                 "Turn on 'Known objects' to see its name.",
    },
    {
        "id": "pluto",
        "title": "Pluto drifts like a Planet X",
        "zoom": "days",
        "ra": 304.1695, "dec": -23.61185, "wave": 1.15, "tol": 0.12, "n": 64,
        "t_min": 60942.0, "t_max": 60962.0,
        "blurb": "Pluto is about 35 times farther from the Sun than Earth. Over three weeks in "
                 "September and October 2025 it drifts about 5 arcminutes (49 SPHEREx pixels), "
                 "only a few pixels a day. A Planet X would move even more slowly. This is exactly "
                 "the kind of patient motion the Days zoom is built to reveal.",
    },
    {
        "id": "ecliptic",
        "title": "The asteroid highway",
        "zoom": "days",
        "ra": 180.0, "dec": 0.0, "wave": None,
        "t_min": None, "t_max": None,
        "blurb": "This patch sits on the ecliptic, the plane where the planets and most asteroids "
                 "orbit. Over a few days, anything that moves between frames is close to us. "
                 "Can you spot something that does not stay put?",
    },
    {
        "id": "m51",
        "title": "A galaxy that should not change",
        "zoom": "months",
        "ra": 202.469575, "dec": 47.19525833, "wave": None,
        "t_min": None, "t_max": None,
        "blurb": "The Whirlpool Galaxy (M51) is 31 million light-years away and will not change in a "
                 "human lifetime. Compare the survey passes in Difference mode: the bright core still "
                 "leaves a red and blue pattern. That is a false change, caused by tiny differences "
                 "in how sharp each image is. Real discoveries have to rule this out.",
    },
    {
        "id": "orion",
        "title": "Orion Nebula across a year",
        "zoom": "year",
        "ra": 83.82208, "dec": -5.39111, "wave": None,
        "t_min": None, "t_max": None,
        "blurb": "A stellar nursery 1,300 light-years away, seen in two survey passes about a year "
                 "apart. Young stars here can flicker in brightness; use the slider to compare.",
    },
]


def stops():
    return [{"tol": None, "n": 48} | s for s in STOPS]


def find(stop_id):
    return next((s for s in stops() if s["id"] == stop_id), None)

# Community Hardware Lab

Technical stewardship for communities, farms and households: make useful systems
straightforward to choose, operate and hand over.

**Early development.** The first code implements onboarding recommendations. It
does not install applications, monitor hardware or grant an agent control.

## Product priorities

1. Prevent serious physical, health and major financial harm.
2. Make the supported system easy to use.
3. Offer proportionate protection and clear choices about privacy, cost, time and control.

Onboarding considers existing skills, setup/monthly budgets, learning time,
ongoing operating time, privacy requirements and desired involvement. It should
recommend what a community can realistically sustain. Fewer resources may mean
fewer supported services; they do not make unlimited autonomous care feasible.
Routine automation should reduce friction within agreed, enforceable boundaries.

People see a short recommendation first. Reasons, alternatives, costs, evidence
and eventually configuration/code remain available through progressive disclosure.
Reading every technical detail is optional; silence is not consent to an unagreed
change. Open source supports inspection and collaboration, not a safety guarantee.

Knowledge Steward is an independent application alongside farmOS, Project NOMAD
and other specialist tools. The Lab helps operate systems; each application keeps
its own records and decision authority. Hermes and Stackarr are intended reusable
components, not required replacements for every existing tool. No integration is
claimed working in this repository yet.

## Run the first module

Python 3.10+; no dependencies, network calls or API keys:

```sh
python3 onboarding.py examples/answers.json examples/options.json
python3 onboarding.py examples/answers.json examples/options.json --details
python3 -m unittest discover -s tests -v
```

**The example options use fictional costs and capabilities.** They demonstrate
recommendation behaviour; they are not packages for sale, hardware advice or
verified deployments. Actual options need assessed effort/cost and evidence from
the intended installation. The evaluator trusts supplied assessment evidence;
it does not independently verify that evidence or turn it into execution rights.

## Next integration

Prove one actual supported disposable service journey using a pinned management
runtime: observe, scoped consent, operation, independent read-back and application
data recovery. Reuse upstream fixes and interfaces before building replacements.
Keep deployment credentials, private records and production resources outside this
repository. A repository is where the project is developed, not a server deployment.

## Licence

Original project code is licensed under **GPL-3.0-only**; see [LICENSE](LICENSE).
Distributed modified versions must preserve the applicable GPL source and licence
obligations. Private use and charging for support are allowed. This is GPL, not
AGPL: network use alone does not trigger a source-distribution requirement.
Existing compliant recipients retain their published licence grants.
See [licence decision and provenance](docs/licence.md).

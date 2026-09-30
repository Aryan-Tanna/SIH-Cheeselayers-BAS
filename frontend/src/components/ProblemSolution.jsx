const items = [
  {
    problem: 'No Real-Time Ground Support',
    problemImpact:
      'Communication delay and restricted bandwidth make raw video streaming to Earth impossible.',
    solution: 'Fully On-Board Intelligence',
    solutionBenefit:
      'Abhay runs entirely on the station — detector, engine, TTS — with zero dependency on Earth.',
  },
  {
    problem: 'Steps Skipped or Done Out of Order',
    problemImpact:
      'A missed step can compromise a scientific experiment with no chance of real-time correction.',
    solution: 'Deterministic Protocol Engine',
    solutionBenefit:
      'A constraint-graph engine raises a spoken alert the instant a skip, out-of-order, or wrong object is detected.',
  },
  {
    problem: 'Raw Video Downlink Is Too Heavy',
    problemImpact:
      'Sending session video to Earth uses 3.6 MB per session — far above the available bandwidth.',
    solution: 'Log + JPEG Downlink (486 KB)',
    solutionBenefit:
      'Only the hash-chained log and one JPEG per step are sent — 7× smaller, tamper-evident, and verified on arrival.',
  },
  {
    problem: 'Neural Networks Can Hallucinate Steps',
    problemImpact:
      'An LLM or neural alert engine can fabricate an action that never happened, blocking the astronaut.',
    solution: 'No Neural Net in the Alert Path',
    solutionBenefit:
      'Vision identifies objects; the deterministic engine decides. Same input always produces the same alert.',
  },
];

export default function ProblemSolution() {
  return (
    <section className="bg-blue-50">
      <div className="max-w-7xl mx-auto px-4 py-20">
        <h2 className="text-3xl font-bold text-center text-gray-900 mb-2">The Problem We Solve</h2>
        <p className="text-center text-gray-500 mb-12">
          Astronauts need real-time procedure guidance — without relying on Earth.
        </p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {items.map((item) => (
            <div key={item.problem} className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
              <div className="flex items-start gap-3 mb-4 pb-4 border-b border-gray-100">
                <span className="text-red-500 text-lg leading-none shrink-0" aria-hidden="true">⚠</span>
                <div>
                  <h3 className="font-semibold text-gray-900">{item.problem}</h3>
                  <p className="text-sm text-gray-600 mt-1">{item.problemImpact}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="text-primary text-lg leading-none shrink-0" aria-hidden="true">✓</span>
                <div>
                  <h3 className="font-semibold text-gray-900">{item.solution}</h3>
                  <p className="text-sm text-gray-600 mt-1">{item.solutionBenefit}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

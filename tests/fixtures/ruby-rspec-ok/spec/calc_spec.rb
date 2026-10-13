# frozen_string_literal: true

require_relative "../lib/calc"

RSpec.describe Calc do
  it "adds" do
    expect(Calc.add(2, 3)).to eq(5)
  end
end

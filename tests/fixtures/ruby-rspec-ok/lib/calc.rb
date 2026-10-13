# frozen_string_literal: true

# Tiny calculator for the ruby-rspec-* fixtures.
module Calc
  def self.add(first, second)
    first + second
  end

  def self.sign(num)
    num.negative? ? -1 : 1
  end
end

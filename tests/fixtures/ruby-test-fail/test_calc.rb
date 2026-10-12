# frozen_string_literal: true

require "minitest/autorun"
require_relative "calc"

class CalcTest < Minitest::Test
  def test_add
    assert_equal 6, add(2, 3)
  end
end

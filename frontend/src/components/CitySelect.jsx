function CitySelect({ value, onChange }) {
  return (
    <label className="city-select">
      <span>所在城市</span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="address-level2"
        placeholder="杭州"
      />
    </label>
  );
}

export default CitySelect;

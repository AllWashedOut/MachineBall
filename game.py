from event import Event
import copy
import numpy as np

class Game(object):
  def __init__(self):
    self.id = 0
    self.date = 0
    self.year = 0
    # [visiting team, home team]
    self.teams = [None, None]
    self.score = [0, 0]
    self.initial_full_roster = [[], []]
    self.initial_starting_roster = [[], []]
    self.players = [set(), set()]
    self.starting_players = [set(), set()]
    # [ team 1 map of position:playerid, team 2 map of position:playerid]
    self.active_players = [{}, {}]
    
    self._last_event_type = None
    
  @classmethod
  def peakNextDate(cls, lines):
    """Given some lines from an event file, finds the date of the next game
    in the lines."""
    for line in lines:
      event_line = Event.from_line(line)
      if event_line.type == Event.Types.id:
        return int(event_line.parts[1][3:])
    return None
    
  def gobble(self, lines, stats_tracker, starters_only=False, full_roster=False, rosters=None):
    """Given some lines from an event file, reads the plays for one game.
    The lines are consumed, so you can call this repeatedly on a list of
    events to parse out all the games."""
    
    # Snapshot all player stats before the game starts. It would be
    # unfair to let the model guess the games score using player stats that
    # already included the game.
    # Unfortunately this is the slowest step in the whole parsing flow.
    if not starters_only and not full_roster:
      initial_stats_tracker = copy.deepcopy(stats_tracker)
      
    # consumes event lines until the game appears to be over
    while not self.id:
      line = lines.pop(0)
      id_event = Event.from_line(line)
      if id_event.type == Event.Types.id:
        self.id = id_event.parts[1]
        print('Parsing game {}'.format(self.id))
        self.date = int(self.id[3:])
        date_prefix = str(self.date)[:1]
        assert date_prefix in ['1', '2'], date_prefix # sanity check that year is like 19xx or 2xxx
        self.year = str(self.date)[:4]
      else:
        print('Skipping line: {}'.format(line))

    while lines:
      # If we've reached another game, reset all current player positions
      # and don't consume the line.
      line = lines[0]
      new_event = Event.from_line(line)
      if new_event.type == Event.Types.id:
        stats_tracker.reset_player_positions()
        break
        
      lines.pop(0)
      
      
      if (self._last_event_type == Event.Types.start and
          new_event.type != Event.Types.start):
        for team in [0, 1]:
          team_roster = rosters[self.year][self.teams[team]]
          # record players for 'starts only' training
          if starters_only:
            for player_id in self.players[team]:
              if stats_tracker.has_player(player_id):
                player_vector = stats_tracker.get_player(player_id).to_vector()
                player_vector.append(team)  # mark visitor/home
                player_vector.append(ord(team_roster[player_id]['batting_hand']))  # mark batting hand
                player_vector.append(ord(team_roster[player_id]['throwing_hand']))  # mark throwing hand
                self.initial_starting_roster[team].append(player_vector)
          elif full_roster:
            for player_id in team_roster:
              if stats_tracker.has_player(player_id):
                player_vector = stats_tracker.get_player(player_id).to_vector()
                player_vector.append(team)  # mark visitor/home
                player_vector.append(ord(team_roster[player_id]['batting_hand']))  # mark batting hand
                player_vector.append(ord(team_roster[player_id]['throwing_hand']))  # mark throwing hand
                player_vector.append(int(player_id in self.starting_players[team])) # mark 1 if player is starting
                self.initial_full_roster[team].append(player_vector)
                
 
      # note home and away teams
      if new_event.type == Event.Types.info:
        if new_event.parts[1] == 'visteam':
          self.teams[0] = new_event.parts[2]
        elif new_event.parts[1] == 'hometeam':
          self.teams[1] = new_event.parts[2]
          
      # track the currently active players
      elif new_event.type in [Event.Types.start, Event.Types.sub]:
        # todo: i dunno if this works for designated hitters, pinch hitters, pinch runners
        _, player_id, _, team, _, position = new_event.parts
        team, position = int(team), int(position)
        self.players[team].add(player_id)
        if new_event.type == Event.Types.start:
          self.starting_players[team].add(player_id)
        if position in self.active_players[team]:
          # the old player needs to be unassigned IF they aren't already
          # in another position.
          stats_tracker.unassign_player(player_id=self.active_players[team][position], old_position=position)
        self.active_players[team][position] = player_id
        stats_tracker.set_player_position(player_id, position)
        
      
      elif new_event.type == Event.Types.play:
        # update score
        score_update = stats_tracker.play(new_event, batter_id=player_id, fielder_ids=self.active_players[team])
        self.score = [sum(x) for x in zip(self.score, score_update)]
        
      self._last_event_type = new_event.type
    
    # Now that we know which players actually saw field time, go back
    # and get their initial stats (before this game was played). This is
    # the training data.
    # If we had no record of a player before this game, then sadly
    # we can't include them.
    if not starters_only and not full_roster:
      for team in [0, 1]:
        for player_id in self.players[team]:
          if initial_stats_tracker.has_player(player_id):
            player_vector = initial_stats_tracker.get_player(player_id).to_vector()
            player_vector.append(team)  # mark visitor/home
            player_vector.append(ord(team_roster[player_id]['batting_hand']))  # mark batting hand
            player_vector.append(ord(team_roster[player_id]['throwing_hand']))  # mark throwing hand
            self.initial_full_roster[team].append(player_vector)
          
  def to_sample(self, starters_only=False):
    """Called after a game has been parsed, returns the initial stats of all
    players and the final score.
    
    Params
      starters_only: train only on the list of starting players, discarding info on subs."""
    assert self.id, 'It appears this game has not been populated. Cannot sample it.'      
     
    if starters_only:
      sample = self.initial_starting_roster[0] + self.initial_starting_roster[1]
    else:
      sample = self.initial_full_roster[0] + self.initial_full_roster[1]
    return sample, self.score[0], self.score[1]
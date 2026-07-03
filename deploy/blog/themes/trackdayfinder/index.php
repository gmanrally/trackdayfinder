<?php if ( ! defined( 'ABSPATH' ) ) exit; get_header(); ?>

<?php if ( have_posts() ) : ?>

	<?php if ( is_home() && ! is_front_page() ) : ?>
		<h1 style="margin-bottom:18px"><?php single_post_title(); ?></h1>
	<?php endif; ?>

	<?php while ( have_posts() ) : the_post(); ?>
		<article class="tdf-post" id="post-<?php the_ID(); ?>">
			<p class="tdf-post-meta">
				<time datetime="<?php echo esc_attr( get_the_date( 'c' ) ); ?>"><?php echo esc_html( get_the_date() ); ?></time>
				<?php if ( get_the_author() ) : ?>
					&middot; by <?php the_author(); ?>
				<?php endif; ?>
				<?php $cats = get_the_category_list( ', ' ); if ( $cats ) : ?>
					&middot; <?php echo $cats; ?>
				<?php endif; ?>
			</p>
			<h2 style="margin-top:0">
				<a href="<?php the_permalink(); ?>" style="color:var(--fg)"><?php the_title(); ?></a>
			</h2>
			<?php the_excerpt(); ?>
			<a href="<?php the_permalink(); ?>" class="tdf-readmore">Read more &rarr;</a>
		</article>
	<?php endwhile; ?>

	<div class="tdf-pagination">
		<?php
		echo paginate_links( array(
			'prev_text' => '&larr; Newer',
			'next_text' => 'Older &rarr;',
		) );
		?>
	</div>

<?php else : ?>

	<article class="tdf-post">
		<h1>Nothing here yet.</h1>
		<p>No posts have been published. Check back soon.</p>
		<form role="search" method="get" class="tdf-search" action="<?php echo esc_url( home_url( '/' ) ); ?>">
			<input type="search" name="s" placeholder="Search posts…" value="<?php echo esc_attr( get_search_query() ); ?>">
			<button type="submit">Search</button>
		</form>
	</article>

<?php endif; ?>

<?php get_footer(); ?>
